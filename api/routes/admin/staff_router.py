from __future__ import annotations

import uuid
from typing import Any

import discord
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from api.routes.admin.security import require_local_admin
from api.schemas.admin import StaffActivityItem, StaffDetail, StaffEvaluationItem, StaffTicketItem
from database.models.claim import Claim
from database.models.evaluation import Evaluation
from database.models.staff import Staff
from database.models.staff_stats import StaffStats
from database.models.ticket import Ticket, TicketStatus
from database.models.ticket_panel import TicketPanel

router = APIRouter(
    prefix="/admin/api",
    tags=["admin-staff"],
    dependencies=[Depends(require_local_admin)],
)


def _bot(request: Request):
    return request.app.state.bot


def _guild(bot: Any, guild_id: int) -> discord.Guild:
    guild = bot.get_guild(guild_id)
    if guild is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "GUILD_NOT_FOUND", "message": "Servidor nao encontrado."}},
        )
    return guild


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _discord_name(guild: discord.Guild, user_id: int | None) -> str | None:
    if user_id is None:
        return None
    member = guild.get_member(user_id)
    return member.display_name if member is not None else None


def _channel_name(bot: Any, channel_id: int | None) -> str | None:
    if channel_id is None:
        return None
    channel = bot.get_channel(channel_id)
    return getattr(channel, "name", None)


def _ticket_label(bot: Any, ticket: Ticket) -> str:
    channel_name = _channel_name(bot, ticket.channel_id)
    return f"#{channel_name}" if channel_name else f"Ticket {str(ticket.id)[:8]}"


def _ticket_category_label(ticket: Ticket, panel_name: str | None) -> str:
    """No painel de staff, o motivo util e o painel real que abriu o ticket.

    Muitos tickets antigos ficaram com category="outro" porque a categoria
    tecnica do banco e generica; quem explica o motivo para a staff e o painel
    de origem, ex.: "Painel Duvida", "Bug", "Parceria". So cai para category
    quando o ticket nao tem painel vinculado.
    """
    return panel_name or ticket.category.value


def _ticket_item(
    bot: Any, guild: discord.Guild, ticket: Ticket, panel_name: str | None = None
) -> StaffTicketItem:
    return StaffTicketItem(
        id=str(ticket.id),
        label=_ticket_label(bot, ticket),
        channel_id=str(ticket.channel_id),
        channel_name=_channel_name(bot, ticket.channel_id),
        user_id=str(ticket.opened_by_discord_id),
        user_name=_discord_name(guild, ticket.opened_by_discord_id),
        category=_ticket_category_label(ticket, panel_name),
        status=ticket.status.value,
        created_at=_iso(ticket.created_at) or "",
        closed_at=_iso(ticket.closed_at),
        first_response_at=_iso(ticket.first_response_at),
    )


@router.get("/guild/{guild_id}/staff/{staff_id}", response_model=StaffDetail)
async def staff_detail(request: Request, guild_id: int, staff_id: uuid.UUID) -> StaffDetail:
    """Perfil completo de staff para o painel web.

    Usa as tabelas e estatisticas existentes: Staff, StaffStats, Ticket,
    Claim e Evaluation. Nao cria sistema paralelo e nao mexe em cargos.
    """
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    async with bot.database.session() as session:
        staff_row = await session.scalar(
            select(Staff).where(Staff.guild_id == guild_id, Staff.id == staff_id)
        )
        if staff_row is None:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "STAFF_NOT_FOUND", "message": "Staff nao encontrado."}},
            )

        stats = await session.scalar(select(StaffStats).where(StaffStats.staff_id == staff_id))
        current_result = await session.execute(
            select(Ticket, TicketPanel.name)
            .outerjoin(TicketPanel, TicketPanel.id == Ticket.panel_id)
            .where(
                Ticket.guild_id == guild_id,
                Ticket.claimed_by_staff_id == staff_id,
                Ticket.status.in_([TicketStatus.OPEN, TicketStatus.CLAIMED]),
            )
            .order_by(Ticket.created_at.desc())
            .limit(10)
        )
        recent_result = await session.execute(
            select(Ticket, TicketPanel.name)
            .outerjoin(TicketPanel, TicketPanel.id == Ticket.panel_id)
            .where(Ticket.guild_id == guild_id, Ticket.claimed_by_staff_id == staff_id)
            .order_by(Ticket.created_at.desc())
            .limit(12)
        )
        evaluation_result = await session.execute(
            select(Evaluation)
            .where(Evaluation.staff_id == staff_id)
            .order_by(Evaluation.created_at.desc())
            .limit(10)
        )
        claim_result = await session.execute(
            select(Claim, Ticket, TicketPanel.name)
            .join(Ticket, Ticket.id == Claim.ticket_id)
            .outerjoin(TicketPanel, TicketPanel.id == Ticket.panel_id)
            .where(Ticket.guild_id == guild_id, Claim.staff_id == staff_id)
            .order_by(Claim.claimed_at.desc())
            .limit(12)
        )

        current_tickets = current_result.all()
        recent_tickets = recent_result.all()
        evaluations = list(evaluation_result.scalars().all())
        claims = claim_result.all()

    metrics = {
        "tickets_assumidos": stats.tickets_assumidos if stats else 0,
        "tickets_fechados": stats.tickets_fechados if stats else 0,
        "tickets_cancelados": stats.tickets_cancelados if stats else 0,
        "avaliacoes_count": stats.avaliacoes_count if stats else 0,
        "avaliacao_media": float(stats.avaliacao_media) if stats else 0.0,
        "melhor_avaliacao": stats.melhor_avaliacao if stats else None,
        "pior_avaliacao": stats.pior_avaliacao if stats else None,
        "tempo_medio_primeira_resposta_s": stats.tempo_medio_primeira_resposta_s if stats else None,
        "tempo_medio_fechamento_s": stats.tempo_medio_fechamento_s if stats else None,
        "current_streak_days": stats.current_streak_days if stats else 0,
        "best_streak_days": stats.best_streak_days if stats else 0,
        "total_active_days": stats.total_active_days if stats else 0,
        "current_day_ticket_count": stats.current_day_ticket_count if stats else 0,
        "best_day_ticket_count": stats.best_day_ticket_count if stats else 0,
        "current_perfect_streak": stats.current_perfect_streak if stats else 0,
        "primeiro_ticket_at": _iso(stats.primeiro_ticket_at) if stats else None,
        "ultimo_ticket_at": _iso(stats.ultimo_ticket_at) if stats else None,
        "last_bad_rating_at": _iso(stats.last_bad_rating_at) if stats else None,
    }

    return StaffDetail(
        id=str(staff_row.id),
        discord_user_id=str(staff_row.discord_user_id),
        display_name=staff_row.display_name,
        active=staff_row.active,
        metrics=metrics,
        current_tickets=[
            _ticket_item(bot, guild, ticket, panel_name) for ticket, panel_name in current_tickets
        ],
        recent_tickets=[
            _ticket_item(bot, guild, ticket, panel_name) for ticket, panel_name in recent_tickets
        ],
        evaluations=[
            StaffEvaluationItem(
                ticket_id=str(item.ticket_id),
                rating=item.rating,
                comment=item.comment,
                rated_by_id=str(item.rated_by_discord_id),
                rated_by_name=_discord_name(guild, item.rated_by_discord_id),
                created_at=_iso(item.created_at) or "",
            )
            for item in evaluations
        ],
        history=[
            StaffActivityItem(
                id=str(claim.id),
                action="Assumiu ticket" if claim.unclaimed_at is None else "Assumiu e liberou ticket",
                created_at=_iso(claim.claimed_at) or "",
                ticket_id=str(ticket.id),
                ticket_label=_ticket_label(bot, ticket),
                detail=_ticket_category_label(ticket, panel_name),
            )
            for claim, ticket, panel_name in claims
        ],
    )
