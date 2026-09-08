from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import discord
from fastapi import APIRouter, Depends, HTTPException, Request

from api.routes.admin.security import require_local_admin
from cogs.giveaways import GiveawayOpenView, close_and_announce, _announce_winners
from database.models.audit_log import AuditLogCategory
from database.models.giveaway import Giveaway, GiveawayPrizeType, GiveawayStatus
from views.embeds import giveaway_panel_embed

router = APIRouter(
    prefix="/admin/api",
    tags=["admin-giveaways"],
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


def _payload_error(message: str, field: str | None = None) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"error": {"code": "INVALID_GIVEAWAY", "message": message, "field": field}},
    )


def _text_channel(guild: discord.Guild, raw: Any, field: str) -> discord.TextChannel:
    try:
        channel_id = int(raw)
    except (TypeError, ValueError) as exc:
        raise _payload_error("Canal invalido.", field) from exc
    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        raise _payload_error("Escolha um canal de texto existente neste servidor.", field)
    return channel


def _role_ids(guild: discord.Guild, raw: Any, field: str) -> list[int]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise _payload_error("Envie uma lista de cargos.", field)
    role_ids: list[int] = []
    for item in raw:
        try:
            role_id = int(item)
        except (TypeError, ValueError) as exc:
            raise _payload_error("Lista de cargos contem ID invalido.", field) from exc
        role = guild.get_role(role_id)
        if role is None or role.is_default():
            raise _payload_error("Um ou mais cargos nao existem ou sao invalidos.", field)
        role_ids.append(role_id)
    return role_ids


def _positive_int(raw: Any, field: str, *, minimum: int = 1, maximum: int | None = None) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise _payload_error("Use um numero inteiro.", field) from exc
    if value < minimum:
        raise _payload_error(f"Use um valor maior ou igual a {minimum}.", field)
    if maximum is not None and value > maximum:
        raise _payload_error(f"Use um valor menor ou igual a {maximum}.", field)
    return value


def _clean_text(raw: Any, field: str, *, required: bool, max_len: int) -> str | None:
    value = str(raw or "").strip()
    if required and not value:
        raise _payload_error("Campo obrigatorio.", field)
    if len(value) > max_len:
        raise _payload_error(f"Use no maximo {max_len} caracteres.", field)
    return value or None


def _member_name(guild: discord.Guild, user_id: int) -> str:
    member = guild.get_member(user_id)
    return member.display_name if member else str(user_id)


async def _serialize_giveaway(bot: Any, guild: discord.Guild, giveaway: Giveaway) -> dict[str, Any]:
    entry_count = await bot.giveaway_service.count_entries(giveaway.id)
    winners = await bot.giveaway_service.list_winners(giveaway.id)
    channel = guild.get_channel(giveaway.channel_id)
    prize_role = guild.get_role(giveaway.prize_role_id) if giveaway.prize_role_id else None
    missing_allowed_roles = [
        str(role_id) for role_id in giveaway.allowed_role_ids if guild.get_role(int(role_id)) is None
    ]
    status = giveaway.status.value if hasattr(giveaway.status, "value") else str(giveaway.status)
    prize_type = giveaway.prize_type.value if hasattr(giveaway.prize_type, "value") else str(giveaway.prize_type)
    return {
        "id": str(giveaway.id),
        "title": giveaway.title,
        "description": giveaway.description,
        "status": status,
        "channel_id": str(giveaway.channel_id),
        "channel_name": getattr(channel, "name", None),
        "channel_missing": channel is None,
        "message_id": str(giveaway.message_id) if giveaway.message_id else None,
        "creator_id": str(giveaway.creator_id),
        "creator_name": _member_name(guild, giveaway.creator_id),
        "winners_count": giveaway.winners_count,
        "entry_count": entry_count,
        "winner_ids": [str(user_id) for user_id in winners],
        "winner_names": [_member_name(guild, user_id) for user_id in winners],
        "allowed_role_ids": [str(role_id) for role_id in giveaway.allowed_role_ids],
        "missing_allowed_role_ids": missing_allowed_roles,
        "prize_type": prize_type,
        "prize_role_id": str(giveaway.prize_role_id) if giveaway.prize_role_id else None,
        "prize_role_name": prize_role.name if prize_role else None,
        "prize_text": giveaway.prize_text,
        "expires_at": giveaway.expires_at.isoformat(),
        "closed_at": giveaway.closed_at.isoformat() if giveaway.closed_at else None,
        "created_at": giveaway.created_at.isoformat() if giveaway.created_at else None,
    }


@router.get("/guild/{guild_id}/giveaways")
async def list_giveaways(request: Request, guild_id: int) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    giveaways = await bot.giveaway_service.list_by_guild(guild_id)
    return {
        "guild_id": str(guild_id),
        "items": [await _serialize_giveaway(bot, guild, giveaway) for giveaway in giveaways],
    }


@router.post("/guild/{guild_id}/giveaways")
async def create_giveaway(request: Request, guild_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    channel = _text_channel(guild, payload.get("channel_id"), "channel_id")
    title = _clean_text(payload.get("title"), "title", required=True, max_len=256)
    description = _clean_text(payload.get("description"), "description", required=False, max_len=500)
    winners_count = _positive_int(payload.get("winners_count", 1), "winners_count", minimum=1, maximum=50)
    duration_minutes = _positive_int(payload.get("duration_minutes"), "duration_minutes", minimum=1, maximum=60 * 24 * 30)
    allowed_role_ids = _role_ids(guild, payload.get("allowed_role_ids", []), "allowed_role_ids")
    raw_prize_type = str(payload.get("prize_type") or "CUSTOM").upper()
    if raw_prize_type not in {GiveawayPrizeType.CUSTOM.value, GiveawayPrizeType.ROLE.value}:
        raise _payload_error("Tipo de premio invalido.", "prize_type")
    prize_type = GiveawayPrizeType(raw_prize_type)
    prize_role_id: int | None = None
    prize_text: str | None = None
    if prize_type == GiveawayPrizeType.ROLE:
        roles = _role_ids(guild, [payload.get("prize_role_id")], "prize_role_id")
        prize_role_id = roles[0]
    else:
        prize_text = _clean_text(payload.get("prize_text"), "prize_text", required=True, max_len=500)

    giveaway = await bot.giveaway_service.create_giveaway(
        guild_id=guild_id,
        creator_id=0,
        channel_id=channel.id,
        title=title or "Sorteio",
        description=description,
        duration=timedelta(minutes=duration_minutes),
        winners_count=winners_count,
        allowed_role_ids=allowed_role_ids,
        prize_type=prize_type,
        prize_role_id=prize_role_id,
        prize_text=prize_text,
    )
    try:
        message = await channel.send(embed=giveaway_panel_embed(giveaway, 0), view=GiveawayOpenView(giveaway.id))
        await bot.giveaway_service.set_message_id(giveaway.id, message.id)
        with contextlib.suppress(discord.HTTPException):
            await message.pin(reason="Painel fixo de sorteio criado pelo dashboard")
    except discord.Forbidden as exc:
        raise HTTPException(
            status_code=403,
            detail={"error": {"code": "DISCORD_FORBIDDEN", "message": "Sem permissao para enviar o sorteio neste canal."}},
        ) from exc
    except discord.HTTPException as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": {"code": "DISCORD_ERROR", "message": "Discord recusou o envio do sorteio."}},
        ) from exc

    await bot.audit_log_service.record(
        guild_id=guild_id,
        category=AuditLogCategory.GIVEAWAY,
        action="SORTEIO_CRIADO_DASHBOARD",
        executor_id=0,
        executor_name="Dashboard local",
        details={"giveaway_id": str(giveaway.id), "title": giveaway.title, "channel_id": channel.id},
    )
    fresh = await bot.giveaway_service.get_giveaway(giveaway.id) or giveaway
    return {"item": await _serialize_giveaway(bot, guild, fresh)}


@router.post("/guild/{guild_id}/giveaways/{giveaway_id}/close")
async def close_giveaway(request: Request, guild_id: int, giveaway_id: uuid.UUID) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    giveaway = await bot.giveaway_service.get_giveaway(giveaway_id)
    if giveaway is None or giveaway.guild_id != guild_id:
        raise HTTPException(status_code=404, detail={"error": {"code": "GIVEAWAY_NOT_FOUND", "message": "Sorteio nao encontrado."}})
    await close_and_announce(bot, giveaway_id)
    fresh = await bot.giveaway_service.get_giveaway(giveaway_id) or giveaway
    return {"item": await _serialize_giveaway(bot, guild, fresh)}


@router.post("/guild/{guild_id}/giveaways/{giveaway_id}/reroll")
async def reroll_giveaway(request: Request, guild_id: int, giveaway_id: uuid.UUID) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    giveaway = await bot.giveaway_service.get_giveaway(giveaway_id)
    if giveaway is None or giveaway.guild_id != guild_id:
        raise HTTPException(status_code=404, detail={"error": {"code": "GIVEAWAY_NOT_FOUND", "message": "Sorteio nao encontrado."}})
    result = await bot.giveaway_service.reroll(giveaway_id)
    if result is None:
        raise HTTPException(status_code=409, detail={"error": {"code": "GIVEAWAY_NOT_CLOSED", "message": "So e possivel rerollar sorteio encerrado."}})
    giveaway, winners = result
    await _announce_winners(bot, giveaway, winners, is_reroll=True)
    await bot.audit_log_service.record(
        guild_id=guild_id,
        category=AuditLogCategory.GIVEAWAY,
        action="SORTEIO_REROLL_DASHBOARD",
        executor_id=0,
        executor_name="Dashboard local",
        details={"giveaway_id": str(giveaway.id), "title": giveaway.title, "winners": winners},
    )
    return {"item": await _serialize_giveaway(bot, guild, giveaway)}


@router.post("/guild/{guild_id}/giveaways/{giveaway_id}/cancel")
async def cancel_giveaway(request: Request, guild_id: int, giveaway_id: uuid.UUID) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    giveaway = await bot.giveaway_service.cancel_giveaway(giveaway_id)
    if giveaway is None or giveaway.guild_id != guild_id:
        raise HTTPException(status_code=404, detail={"error": {"code": "GIVEAWAY_NOT_FOUND", "message": "Sorteio aberto nao encontrado."}})
    channel = guild.get_channel(giveaway.channel_id)
    if giveaway.message_id is not None and isinstance(channel, discord.TextChannel):
        with contextlib.suppress(discord.HTTPException):
            message = await channel.fetch_message(giveaway.message_id)
            await message.edit(content="Sorteio cancelado pelo Dashboard local.", view=None)
    await bot.audit_log_service.record(
        guild_id=guild_id,
        category=AuditLogCategory.GIVEAWAY,
        action="SORTEIO_CANCELADO_DASHBOARD",
        executor_id=0,
        executor_name="Dashboard local",
        details={"giveaway_id": str(giveaway.id), "title": giveaway.title},
    )
    return {"item": await _serialize_giveaway(bot, guild, giveaway)}
