from __future__ import annotations

import platform
import re
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from math import ceil, isfinite
from pathlib import Path
from typing import Any, Literal

import discord
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import String, cast, func, or_, select, text

from api.routes.admin.security import require_local_admin
from api.schemas.admin import (
    ActivityItem,
    AdminGuild,
    AdminHealth,
    AdminReadiness,
    AuditDetail,
    AuditListResponse,
    DiscordOption,
    OverviewMetric,
    OverviewResponse,
    RankingRow,
    SettingDefinition,
    SettingOption,
    SettingsPayload,
    SettingsSection,
    SettingsUpdateRequest,
    StaffRow,
    SystemResponse,
    SystemStatus,
    TicketClaimItem,
    TicketDetail,
    TicketEvaluationItem,
    TicketListResponse,
    TicketRow,
)
from core.logger import get_logger
from database.models.audit_log import AuditLogCategory, AuditLogEntry
from database.models.claim import Claim
from database.models.evaluation import Evaluation
from database.models.staff import Staff
from database.models.staff_stats import StaffStats
from database.models.ticket import Ticket, TicketCategory, TicketStatus
from services.ranking_service import RankingPeriod
from views.master_config_view import iter_categories
from views.settings_panel import FieldKind, SettingsField

router = APIRouter(
    prefix="/admin/api",
    tags=["admin"],
    dependencies=[Depends(require_local_admin)],
)

_ROOT = Path(__file__).resolve().parents[3]
logger = get_logger("admin_api")

_CATEGORY_DESCRIPTIONS = {
    "tickets": "Comportamento, canais e automacoes do atendimento.",
    "cargos": "Cargos base usados pelas regras do bot.",
    "permissoes": "Quem pode executar acoes administrativas e de ticket.",
    "ranking": "Criterio, periodo e publicacao do ranking.",
    "avaliacoes": "Coleta, destino e mensagem de avaliacao.",
    "antispam": "Limites de flood e alerta de spam.",
    "moderacao": "Canais, recursos e limites de moderacao.",
    "verificacao": "Fluxo de verificacao e mensagens do CAPTCHA.",
}

_FIELD_DESCRIPTIONS = {
    "ticket_category_id": "Categoria onde novos tickets serao criados.",
    "log_channel_id": "Destino dos logs operacionais.",
    "transcript_channel_id": "Destino das transcricoes ao fechar tickets.",
    "evaluations_channel_id": "Destino das avaliacoes enviadas por usuarios.",
    "ticket_alert_channel_id": "Canal avisado quando ticket novo abre.",
    "blacklist_channel_id": "Canal usado para alertas de blacklist e spam.",
    "max_tickets_per_user": "Limite de tickets abertos por usuario.",
    "allow_multiple_tickets": "Permite mais de um ticket aberto pelo mesmo usuario.",
    "auto_close_enabled": "Permite fechamento automatico por inatividade.",
    "inactive_after_minutes": "Tempo sem atividade antes de considerar inativo.",
    "delete_delay_seconds": "Espera antes de excluir canal depois do fechamento.",
    "criteria": "Ordenacao principal do ranking.",
    "default_period": "Periodo padrao usado nas consultas de ranking.",
    "enabled": "Liga ou desliga este modulo.",
    "min_comment_rating": "Nota que torna comentario obrigatorio.",
    "evaluation_method": "Onde o usuario recebe a acao de avaliar.",
}


def _bot(request: Request):
    return request.app.state.bot


def _readiness(bot: Any) -> AdminReadiness:
    discord_closed = bool(bot.is_closed())
    discord_ready = bool(bot.is_ready()) if hasattr(bot, "is_ready") else False
    guild_count = len(getattr(bot, "guilds", []) or [])
    guilds_loaded = discord_ready and guild_count > 0
    return AdminReadiness(
        api=True,
        discord_ready=discord_ready,
        discord_closed=discord_closed,
        guilds_loaded=guilds_loaded,
        guild_count=guild_count,
        ready=(not discord_closed) and discord_ready and guilds_loaded,
    )


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat() if dt else None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"error": {"code": "INVALID_DATE", "message": "Data invalida."}}) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _pages(total: int, page_size: int) -> int:
    return ceil(total / page_size) if total else 0


def _latency_ms(bot: Any) -> int:
    latency = float(getattr(bot, "latency", 0) or 0)
    if not isfinite(latency):
        return 0
    return round(latency * 1000)


def _clean_label(value: str) -> str:
    value = re.sub(r"^[^\w]+", "", value, flags=re.UNICODE).strip()
    return value.replace("  ", " ")


def _field_type(field: SettingsField) -> str:
    return {
        FieldKind.CHANNEL: "channel",
        FieldKind.ROLE: "role",
        FieldKind.ROLE_MULTI: "role_multi",
        FieldKind.NUMBER: "number",
        FieldKind.BOOL: "bool",
        FieldKind.CHOICE: "choice",
        FieldKind.TEXT: "text",
    }[field.kind]


def _setting_definition(section: str, field: SettingsField) -> SettingDefinition:
    return SettingDefinition(
        key=field.attr,
        label=_clean_label(field.label),
        description=_FIELD_DESCRIPTIONS.get(field.attr, ""),
        type=_field_type(field),
        section=section,
        options=[
            SettingOption(value=str(value), label=_clean_label(label))
            for value, label in (field.choices or [])
        ],
        required=field.kind == FieldKind.NUMBER and not field.allow_clear,
    )


def _serialize_value(raw: Any) -> Any:
    if isinstance(raw, uuid.UUID):
        return str(raw)
    if isinstance(raw, datetime):
        return _iso(raw)
    if isinstance(raw, list):
        return [str(item) if isinstance(item, int) else item for item in raw]
    if isinstance(raw, int):
        return str(raw)
    return raw


def _coerce_value(field: SettingsField, value: Any) -> Any:
    if value == "":
        value = None
    if field.kind in {FieldKind.CHANNEL, FieldKind.ROLE}:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("ID invalido.") from exc
    if field.kind == FieldKind.ROLE_MULTI:
        if not isinstance(value, list):
            raise ValueError("Lista de cargos invalida.")
        try:
            return [int(item) for item in value]
        except (TypeError, ValueError) as exc:
            raise ValueError("Lista de cargos contem ID invalido.") from exc
    if field.kind == FieldKind.NUMBER:
        if value is None:
            if not field.allow_clear:
                raise ValueError("Campo obrigatorio.")
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Use um numero inteiro.") from exc
        if parsed < 0:
            raise ValueError("Use zero ou numero positivo.")
        return parsed
    if field.kind == FieldKind.BOOL:
        if not isinstance(value, bool):
            raise ValueError("Use verdadeiro ou falso.")
        return value
    if field.kind == FieldKind.CHOICE:
        raw = str(value)
        allowed = {str(option) for option, _ in (field.choices or [])}
        if raw not in allowed:
            raise ValueError("Opcao invalida.")
        return raw
    if field.kind == FieldKind.TEXT:
        return str(value).strip() or None
    return value


async def _settings_bundle(bot, guild_id: int) -> tuple[list[SettingsSection], dict[str, Any], dict[str, Any]]:
    sections: list[SettingsSection] = []
    values: dict[str, Any] = {}
    updaters: dict[str, Any] = {}
    for key, title, fields, get_settings, update_settings in iter_categories(bot):
        if key not in _CATEGORY_DESCRIPTIONS:
            continue
        settings = await get_settings(guild_id)
        section_title = _clean_label(title)
        sections.append(
            SettingsSection(
                key=key,
                title=section_title,
                description=_CATEGORY_DESCRIPTIONS[key],
                fields=[_setting_definition(section_title, field) for field in fields],
            )
        )
        for field in fields:
            values[field.attr] = _serialize_value(getattr(settings, field.attr))
            updaters[field.attr] = (field, update_settings, section_title)
    return sections, values, updaters


def _guild(bot, guild_id: int | None = None) -> discord.Guild | None:
    if guild_id is not None:
        return bot.get_guild(guild_id)
    if bot.settings.test_guild_id is not None:
        guild = bot.get_guild(bot.settings.test_guild_id)
        if guild is not None:
            return guild
    return bot.guilds[0] if bot.guilds else None


def _admin_guild(guild: discord.Guild, *, selected: bool = False) -> AdminGuild:
    return AdminGuild(
        id=str(guild.id),
        name=guild.name,
        icon_url=str(guild.icon.url) if guild.icon else None,
        member_count=guild.member_count,
        selected=selected,
    )


def _discord_name(guild: discord.Guild | None, user_id: int | None) -> str | None:
    if guild is None or user_id is None:
        return None
    get_member = getattr(guild, "get_member", None)
    if get_member is None:
        return None
    member = get_member(user_id)
    if member is not None:
        return member.display_name
    return None


def _channel_name(bot: Any, channel_id: int | None) -> str | None:
    if channel_id is None:
        return None
    channel = bot.get_channel(channel_id)
    return getattr(channel, "name", None)


def _ticket_label(ticket: Ticket, bot: Any) -> str:
    channel_name = _channel_name(bot, ticket.channel_id)
    if channel_name:
        return f"#{channel_name}"
    return f"Ticket {str(ticket.id)[:8]}"


@router.get("/health", response_model=AdminHealth)
async def admin_health(request: Request) -> AdminHealth:
    return AdminHealth(
        status="ok",
        local_only=True,
        client_host=request.client.host if request.client else None,
    )


@router.get("/ready", response_model=AdminReadiness)
async def admin_ready(request: Request) -> AdminReadiness:
    ready = _readiness(_bot(request))
    if ready.ready and not getattr(request.app.state, "admin_ready_logged", False):
        logger.info("Readiness admin atingido: guilds=%s.", ready.guild_count)
        request.app.state.admin_ready_logged = True
    return ready


@router.get("/guilds", response_model=list[AdminGuild])
async def guilds(request: Request) -> list[AdminGuild]:
    bot = _bot(request)
    selected = _guild(bot)
    return [_admin_guild(guild, selected=selected is not None and guild.id == selected.id) for guild in bot.guilds]


@router.get("/guild/{guild_id}/discord-options", response_model=dict[str, list[DiscordOption]])
async def discord_options(request: Request, guild_id: int) -> dict[str, list[DiscordOption]]:
    guild = _guild(_bot(request), guild_id)
    if guild is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "GUILD_NOT_FOUND", "message": "Servidor nao encontrado."}})
    channels = [
        DiscordOption(id=str(ch.id), name=ch.name, type=str(ch.type), position=ch.position)
        for ch in guild.channels
        if isinstance(ch, (discord.TextChannel, discord.CategoryChannel, discord.VoiceChannel, discord.ForumChannel))
    ]
    roles = [
        DiscordOption(
            id=str(role.id),
            name=role.name,
            type="role",
            position=role.position,
            color=f"#{role.color.value:06x}",
        )
        for role in sorted(guild.roles, key=lambda item: item.position, reverse=True)
        if not role.is_default()
    ]
    return {"channels": channels, "roles": roles}


@router.get("/guild/{guild_id}/settings", response_model=SettingsPayload)
async def get_settings(request: Request, guild_id: int) -> SettingsPayload:
    if _guild(_bot(request), guild_id) is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "GUILD_NOT_FOUND", "message": "Servidor nao encontrado."}})
    sections, values, _ = await _settings_bundle(_bot(request), guild_id)
    return SettingsPayload(guild_id=str(guild_id), sections=sections, values=values)


@router.patch("/guild/{guild_id}/settings", response_model=SettingsPayload)
async def update_settings(request: Request, guild_id: int, payload: SettingsUpdateRequest) -> SettingsPayload:
    bot = _bot(request)
    if _guild(bot, guild_id) is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "GUILD_NOT_FOUND", "message": "Servidor nao encontrado."}})
    _, before, updaters = await _settings_bundle(bot, guild_id)
    grouped: dict[Any, dict[str, Any]] = {}
    changes: list[tuple[str, str, Any, Any]] = []
    for key, raw in payload.values.items():
        if key not in updaters:
            raise HTTPException(status_code=400, detail={"error": {"code": "INVALID_SETTING", "message": "Configuracao desconhecida.", "field": key}})
        field, updater, section = updaters[key]
        try:
            value = _coerce_value(field, raw)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"error": {"code": "INVALID_SETTING", "message": str(exc), "field": key}}) from exc
        grouped.setdefault(updater, {})[key] = value
        if before.get(key) != _serialize_value(value):
            changes.append((section, field.label, before.get(key), _serialize_value(value)))
    for updater, values in grouped.items():
        await updater(guild_id, **values)
    for section, label, old, new in changes:
        await bot.audit_log_service.record_config_change(
            guild_id=guild_id,
            actor_id=0,
            actor_name="Dashboard local",
            config_category=section,
            config_name=_clean_label(label),
            old_value=str(old),
            new_value=str(new),
        )
    sections, values, _ = await _settings_bundle(bot, guild_id)
    return SettingsPayload(guild_id=str(guild_id), sections=sections, values=values)


@router.get("/overview", response_model=OverviewResponse)
async def overview(request: Request, guild_id: int | None = None) -> OverviewResponse:
    bot = _bot(request)
    readiness = _readiness(bot)
    guild = _guild(bot, guild_id)
    now = datetime.now(UTC)
    metrics: list[OverviewMetric] = []
    activity: list[ActivityItem] = []
    if guild is not None:
        async with bot.database.session() as session:
            open_count = await session.scalar(select(func.count(Ticket.id)).where(Ticket.guild_id == guild.id, Ticket.status.in_([TicketStatus.OPEN, TicketStatus.CLAIMED])))
            today_count = await session.scalar(select(func.count(Ticket.id)).where(Ticket.guild_id == guild.id, Ticket.created_at >= now.replace(hour=0, minute=0, second=0, microsecond=0)))
            staff_count = await session.scalar(select(func.count(Staff.id)).where(Staff.guild_id == guild.id))
            avg_rating = await session.scalar(select(func.avg(Evaluation.rating)).join(Staff, Staff.id == Evaluation.staff_id).where(Staff.guild_id == guild.id))
            recent = await session.execute(select(AuditLogEntry).where(AuditLogEntry.guild_id == guild.id).order_by(AuditLogEntry.created_at.desc()).limit(8))
        metrics = [
            OverviewMetric(label="Tickets abertos", value=int(open_count or 0)),
            OverviewMetric(label="Tickets hoje", value=int(today_count or 0)),
            OverviewMetric(label="Staff ativo", value=int(staff_count or 0)),
            OverviewMetric(label="Avaliacao media", value=round(float(avg_rating or 0), 2)),
        ]
        activity = [
            ActivityItem(
                id=str(item.id),
                title=item.action,
                category=item.category.value,
                created_at=_iso(item.created_at) or "",
                actor=item.executor_name,
                target=item.target_name,
            )
            for item in recent.scalars().all()
        ]
    db_status: Literal["online", "degraded", "offline"] = "online"
    db_detail = "Conectado"
    try:
        start = datetime.now(UTC)
        await bot.database.check_connection()
        db_detail = f"{int((datetime.now(UTC) - start).total_seconds() * 1000)} ms"
    except Exception:
        db_status = "offline"
        db_detail = "Falha na conexao"
    return OverviewResponse(
        guild=_admin_guild(guild, selected=True) if guild else None,
        bot={
            "connected": readiness.ready,
            "discord_ready": readiness.discord_ready,
            "guilds_loaded": readiness.guilds_loaded,
            "guild_count": readiness.guild_count,
            "user": str(bot.user) if bot.user else None,
            "latency_ms": _latency_ms(bot),
            "uptime_seconds": int((now - bot.started_at).total_seconds()),
        },
        metrics=metrics,
        activity=activity,
        health=[
            SystemStatus(
                name="Discord Gateway",
                status="online" if readiness.ready else "degraded",
                detail=f"{readiness.guild_count} guild(s), {_latency_ms(bot)} ms"
                if readiness.discord_ready
                else "Inicializando",
            ),
            SystemStatus(name="Database", status=db_status, detail=db_detail),
            SystemStatus(name="API", status="online", detail=f"127.0.0.1:{bot.settings.api_port}"),
        ],
    )


@router.get("/guild/{guild_id}/tickets", response_model=TicketListResponse)
async def tickets(
    request: Request,
    guild_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    status_filter: str | None = Query(default="active", alias="status"),
    category: TicketCategory | None = None,
    staff_id: str | None = None,
    evaluated: bool | None = None,
    search: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
) -> TicketListResponse:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    if guild is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "GUILD_NOT_FOUND", "message": "Servidor nao encontrado."}})

    offset = (page - 1) * page_size
    created_from_dt = _parse_dt(created_from)
    created_to_dt = _parse_dt(created_to)
    async with bot.database.session() as session:
        query = (
            select(Ticket, Staff.display_name, Evaluation.id)
            .outerjoin(Staff, Ticket.claimed_by_staff_id == Staff.id)
            .outerjoin(Evaluation, Evaluation.ticket_id == Ticket.id)
            .where(Ticket.guild_id == guild_id)
        )
        count_query = (
            select(func.count(Ticket.id))
            .outerjoin(Staff, Ticket.claimed_by_staff_id == Staff.id)
            .outerjoin(Evaluation, Evaluation.ticket_id == Ticket.id)
            .where(Ticket.guild_id == guild_id)
        )
        filters = []
        if status_filter and status_filter != "all":
            normalized = status_filter.lower()
            if normalized in {"open", "active"}:
                filters.append(Ticket.status.in_([TicketStatus.OPEN, TicketStatus.CLAIMED]))
            else:
                try:
                    filters.append(Ticket.status == TicketStatus(normalized))
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail={"error": {"code": "INVALID_STATUS", "message": "Status invalido.", "field": "status"}}) from exc
        if category is not None:
            filters.append(Ticket.category == category)
        if staff_id == "unassigned":
            filters.append(Ticket.claimed_by_staff_id.is_(None))
        elif staff_id:
            try:
                filters.append(Ticket.claimed_by_staff_id == uuid.UUID(staff_id))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail={"error": {"code": "INVALID_STAFF", "message": "Responsavel invalido.", "field": "staff_id"}}) from exc
        if evaluated is True:
            filters.append(Evaluation.id.is_not(None))
        elif evaluated is False:
            filters.append(Evaluation.id.is_(None))
        if created_from_dt is not None:
            filters.append(Ticket.created_at >= created_from_dt)
        if created_to_dt is not None:
            filters.append(Ticket.created_at <= created_to_dt)
        if search:
            like = f"%{search.strip()}%"
            search_filters = [
                cast(Ticket.id, String).ilike(like),
                cast(Ticket.channel_id, String).ilike(like),
                cast(Ticket.opened_by_discord_id, String).ilike(like),
                Staff.display_name.ilike(like),
            ]
            filters.append(or_(*search_filters))
        for item in filters:
            query = query.where(item)
            count_query = count_query.where(item)
        total = int(await session.scalar(count_query) or 0)
        result = await session.execute(query.order_by(Ticket.created_at.desc()).limit(page_size).offset(offset))
        rows = result.all()
    return TicketListResponse(
        items=[
            TicketRow(
                id=str(ticket.id),
                label=_ticket_label(ticket, bot),
                channel_id=str(ticket.channel_id),
                channel_name=_channel_name(bot, ticket.channel_id),
                user_id=str(ticket.opened_by_discord_id),
                user_name=_discord_name(guild, ticket.opened_by_discord_id),
                category=ticket.category.value,
                status=ticket.status.value,
                staff_id=str(ticket.claimed_by_staff_id) if ticket.claimed_by_staff_id else None,
                staff_name=staff_name,
                created_at=_iso(ticket.created_at) or "",
                closed_at=_iso(ticket.closed_at),
                last_activity_at=_iso(ticket.first_response_at or ticket.created_at),
                has_evaluation=evaluation_id is not None,
            )
            for ticket, staff_name, evaluation_id in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
        pages=_pages(total, page_size),
    )


@router.get("/guild/{guild_id}/tickets/{ticket_id}", response_model=TicketDetail)
async def ticket_detail(request: Request, guild_id: int, ticket_id: uuid.UUID) -> TicketDetail:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    if guild is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "GUILD_NOT_FOUND", "message": "Servidor nao encontrado."}})
    async with bot.database.session() as session:
        ticket_result = await session.execute(
            select(Ticket, Staff.display_name)
            .outerjoin(Staff, Ticket.claimed_by_staff_id == Staff.id)
            .where(Ticket.guild_id == guild_id, Ticket.id == ticket_id)
        )
        row = ticket_result.first()
        if row is None:
            raise HTTPException(status_code=404, detail={"error": {"code": "TICKET_NOT_FOUND", "message": "Ticket nao encontrado."}})
        ticket, staff_name = row
        claim_result = await session.execute(
            select(Claim, Staff.display_name)
            .outerjoin(Staff, Claim.staff_id == Staff.id)
            .where(Claim.ticket_id == ticket.id)
            .order_by(Claim.claimed_at.desc())
        )
        claims = claim_result.all()
        evaluation_result = await session.execute(
            select(Evaluation).where(Evaluation.ticket_id == ticket.id)
        )
        evaluation = evaluation_result.scalar_one_or_none()
    return TicketDetail(
        id=str(ticket.id),
        label=_ticket_label(ticket, bot),
        channel_id=str(ticket.channel_id),
        channel_name=_channel_name(bot, ticket.channel_id),
        user_id=str(ticket.opened_by_discord_id),
        user_name=_discord_name(guild, ticket.opened_by_discord_id),
        category=ticket.category.value,
        status=ticket.status.value,
        staff_id=str(ticket.claimed_by_staff_id) if ticket.claimed_by_staff_id else None,
        staff_name=staff_name,
        created_at=_iso(ticket.created_at) or "",
        first_response_at=_iso(ticket.first_response_at),
        closed_at=_iso(ticket.closed_at),
        closed_by_id=str(ticket.closed_by_discord_id) if ticket.closed_by_discord_id else None,
        closed_by_name=_discord_name(guild, ticket.closed_by_discord_id),
        last_activity_at=_iso(ticket.first_response_at or ticket.closed_at or ticket.created_at),
        deleted_before_service=ticket.deleted_before_service,
        counts_for_stats=ticket.counts_for_stats,
        voice_channel_id=str(ticket.voice_channel_id) if ticket.voice_channel_id else None,
        voice_channel_name=_channel_name(bot, ticket.voice_channel_id),
        panel_id=str(ticket.panel_id) if ticket.panel_id else None,
        approval_status=ticket.approval_status.value,
        approval_reviewed_by=str(ticket.approval_reviewed_by) if ticket.approval_reviewed_by else None,
        approval_reviewed_by_name=_discord_name(guild, ticket.approval_reviewed_by),
        approval_reviewed_at=_iso(ticket.approval_reviewed_at),
        claims=[
            TicketClaimItem(
                staff_id=str(claim.staff_id),
                staff_name=claim_staff_name,
                claimed_at=_iso(claim.claimed_at) or "",
                unclaimed_at=_iso(claim.unclaimed_at),
            )
            for claim, claim_staff_name in claims
        ],
        evaluation=TicketEvaluationItem(
            rating=evaluation.rating,
            comment=evaluation.comment,
            rated_by_id=str(evaluation.rated_by_discord_id),
            rated_by_name=_discord_name(guild, evaluation.rated_by_discord_id),
            created_at=_iso(evaluation.created_at) or "",
        ) if evaluation is not None else None,
    )


@router.get("/guild/{guild_id}/staff", response_model=list[StaffRow])
async def staff(request: Request, guild_id: int) -> list[StaffRow]:
    bot = _bot(request)
    async with bot.database.session() as session:
        result = await session.execute(
            select(Staff, StaffStats)
            .join(StaffStats, StaffStats.staff_id == Staff.id)
            .where(Staff.guild_id == guild_id)
            .order_by(StaffStats.tickets_fechados.desc())
        )
        return [
            StaffRow(
                id=str(staff.id),
                discord_user_id=str(staff.discord_user_id),
                display_name=staff.display_name,
                tickets=stats.tickets_fechados,
                average_rating=float(stats.avaliacao_media),
                streak=stats.current_streak_days,
                last_activity_at=_iso(stats.ultimo_ticket_at),
            )
            for staff, stats in result.all()
        ]


@router.get("/guild/{guild_id}/ranking", response_model=list[RankingRow])
async def ranking(request: Request, guild_id: int, period: RankingPeriod = RankingPeriod.ALLTIME) -> list[RankingRow]:
    entries = await _bot(request).ranking_service.compute(guild_id, period)
    return [
        RankingRow(staff_id=str(entry.staff.id), name=entry.staff.display_name, tickets=entry.tickets, average_rating=entry.avaliacao_media)
        for entry in entries
    ]


@router.post("/guild/{guild_id}/ranking/publish", response_model=dict[str, str | bool])
async def publish_ranking(request: Request, guild_id: int) -> dict[str, str | bool]:
    ok, message = await _bot(request).painel_service.publish_ranking(guild_id)
    return {"ok": ok, "message": message}


@router.get("/guild/{guild_id}/audit", response_model=AuditListResponse)
async def audit(
    request: Request,
    guild_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    category: AuditLogCategory | None = None,
    executor_id: int | None = None,
    target_id: int | None = None,
    action: str | None = None,
    search: str | None = None,
    since: str | None = None,
) -> AuditListResponse:
    bot = _bot(request)
    if _guild(bot, guild_id) is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "GUILD_NOT_FOUND", "message": "Servidor nao encontrado."}})
    bounded = max(1, min(page_size, 100))
    offset = (page - 1) * bounded
    since_dt = _parse_dt(since)
    items = await bot.audit_log_service.list_entries(
        guild_id,
        category=category,
        executor_id=executor_id,
        target_id=target_id,
        action=action,
        search=search,
        since=since_dt,
        limit=bounded,
        offset=offset,
    )
    total = await bot.audit_log_service.count_entries(
        guild_id,
        category=category,
        executor_id=executor_id,
        target_id=target_id,
        action=action,
        search=search,
        since=since_dt,
    )
    return AuditListResponse(
        total=total,
        page=page,
        page_size=bounded,
        pages=_pages(total, bounded),
        items=[
            ActivityItem(id=str(item.id), title=item.action, category=item.category.value, created_at=_iso(item.created_at) or "", actor=item.executor_name, target=item.target_name)
            for item in items
        ],
    )


@router.get("/guild/{guild_id}/audit/{audit_id}", response_model=AuditDetail)
async def audit_detail(request: Request, guild_id: int, audit_id: uuid.UUID) -> AuditDetail:
    bot = _bot(request)
    if _guild(bot, guild_id) is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "GUILD_NOT_FOUND", "message": "Servidor nao encontrado."}})
    item = await bot.audit_log_service.get_entry(guild_id, audit_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "AUDIT_NOT_FOUND", "message": "Evento nao encontrado."}})
    return AuditDetail(
        id=str(item.id),
        action=item.action,
        category=item.category.value,
        created_at=_iso(item.created_at) or "",
        executor_id=str(item.executor_id) if item.executor_id else None,
        executor_name=item.executor_name,
        target_id=str(item.target_id) if item.target_id else None,
        target_name=item.target_name,
        reason=item.reason,
        config_category=item.config_category,
        config_name=item.config_name,
        old_value=item.old_value,
        new_value=item.new_value,
        details=item.details or {},
    )


@router.get("/guild/{guild_id}/automod", response_model=dict[str, Any])
async def automod(request: Request, guild_id: int) -> dict[str, Any]:
    bot = _bot(request)
    settings = await bot.automod_service.get_settings(guild_id)
    words = await bot.automod_service.list_effective_words(guild_id)
    logs = await bot.automod_service.list_logs(guild_id, limit=20)
    return {
        "settings": {
            "enabled": settings.enabled,
            "medio_timeout_minutes": settings.medio_timeout_minutes,
            "alto_timeout_minutes": settings.alto_timeout_minutes,
            "alto_use_ban": settings.alto_use_ban,
            "alert_channel_id": str(settings.alert_channel_id) if settings.alert_channel_id else None,
            "ignored_channel_ids": [str(v) for v in settings.ignored_channel_ids],
            "ignored_role_ids": [str(v) for v in settings.ignored_role_ids],
            "allowed_words": settings.allowed_words,
        },
        "words": [{"word": w.palavra, "category": w.categoria.value, "risk": w.nivel.value, "builtin": w.is_builtin} for w in words[:200]],
        "logs": [{"id": str(log.id), "word": log.palavra_detectada, "action": log.punicao_aplicada, "created_at": _iso(log.created_at)} for log in logs],
    }


@router.get("/guild/{guild_id}/panels", response_model=dict[str, Any])
async def panels(request: Request, guild_id: int) -> dict[str, Any]:
    bot = _bot(request)
    ticket_panels = await bot.ticket_panel_service.list_panels(guild_id)
    groups = await bot.ticket_panel_service.list_groups(guild_id)
    return {
        "ticket_panels": [
            {
                "id": str(panel.id),
                "name": panel.name,
                "key": panel.key,
                "enabled": panel.enabled,
                "published": panel.channel_id is not None and panel.message_id is not None,
            }
            for panel in ticket_panels
        ],
        "groups": [{"id": str(group.id), "name": group.name, "published": group.channel_id is not None and group.message_id is not None} for group in groups],
    }


@router.get("/system", response_model=SystemResponse)
async def system(request: Request) -> SystemResponse:
    bot = _bot(request)
    readiness = _readiness(bot)
    db: dict[str, object] = {"connected": True, "latency_ms": None}
    try:
        start = datetime.now(UTC)
        async with bot.database.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db["latency_ms"] = int((datetime.now(UTC) - start).total_seconds() * 1000)
    except Exception:
        db["connected"] = False
    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=_ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        commit = None
    return SystemResponse(
        bot={
            "connected": readiness.ready,
            "discord_ready": readiness.discord_ready,
            "guilds_loaded": readiness.guilds_loaded,
            "user": str(bot.user) if bot.user else None,
            "guilds": readiness.guild_count,
            "latency_ms": _latency_ms(bot),
            "uptime_seconds": int((datetime.now(UTC) - bot.started_at).total_seconds()),
        },
        api={"host": "127.0.0.1", "port": bot.settings.api_port, "environment": bot.settings.environment},
        database=db,
        version={"commit": commit, "python": platform.python_version(), "discord_py": discord.__version__, "platform": sys.platform},
    )
