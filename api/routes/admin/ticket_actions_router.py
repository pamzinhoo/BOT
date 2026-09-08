from __future__ import annotations

import uuid
from typing import Any

import discord
from fastapi import APIRouter, Depends, HTTPException, Request

from api.routes.admin.security import require_local_admin
from database.models.audit_log import AuditLogCategory
from database.models.log import LogAction
from database.models.ticket import Ticket, TicketStatus
from services.claim_service import ClaimError
from services.ticket_service import TicketNotClaimedError, TicketNotFoundError

router = APIRouter(
    prefix="/admin/api",
    tags=["admin-ticket-actions"],
    dependencies=[Depends(require_local_admin)],
)

_DASHBOARD_ACTOR = "Painel web"


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


def _ticket_error(message: str, *, status_code: int = 422) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": "INVALID_TICKET_ACTION", "message": message}},
    )


async def _ticket_by_id(bot: Any, guild_id: int, ticket_id: uuid.UUID) -> Ticket:
    ticket = await bot.ticket_service.get_by_id(ticket_id)
    if ticket is None or ticket.guild_id != guild_id:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "TICKET_NOT_FOUND", "message": "Ticket nao encontrado."}},
        )
    return ticket


def _channel(guild: discord.Guild, ticket: Ticket) -> discord.TextChannel | None:
    channel = guild.get_channel(ticket.channel_id)
    return channel if isinstance(channel, discord.TextChannel) else None


def _status_label(ticket: Ticket) -> str:
    return {
        TicketStatus.OPEN: "Aberto",
        TicketStatus.CLAIMED: "Em atendimento",
        TicketStatus.CLOSED: "Fechado",
        TicketStatus.CANCELLED: "Cancelado",
    }.get(ticket.status, ticket.status.value)


async def _staff_from_payload(bot: Any, guild_id: int, payload: dict[str, Any]) -> Any:
    raw_staff_id = payload.get("staff_id")
    if not raw_staff_id:
        raise _ticket_error("Escolha um membro da staff.")
    try:
        staff_id = uuid.UUID(str(raw_staff_id))
    except ValueError as exc:
        raise _ticket_error("Staff invalido.") from exc
    staff = await bot.staff_service.get_by_id(staff_id)
    if staff is None or staff.guild_id != guild_id:
        raise _ticket_error("Staff nao encontrado neste servidor.")
    return staff


async def _audit(bot: Any, guild_id: int, action: str, ticket: Ticket, details: dict[str, object] | None = None) -> None:
    bot.audit_log_service.record_background(
        guild_id=guild_id,
        category=AuditLogCategory.TICKETS,
        action=action,
        executor_id=None,
        executor_name=_DASHBOARD_ACTOR,
        target_id=ticket.opened_by_discord_id,
        details={"ticket_id": str(ticket.id), "channel_id": ticket.channel_id, **(details or {})},
    )


async def _notify_channel(channel: discord.TextChannel | None, message: str) -> None:
    if channel is None:
        return
    try:
        await channel.send(message)
    except discord.HTTPException:
        return


async def _after_ticket_change(bot: Any, guild_id: int) -> None:
    await bot.painel_service.refresh_dashboard(guild_id)


@router.post("/guild/{guild_id}/tickets/{ticket_id}/claim")
async def claim_ticket(request: Request, guild_id: int, ticket_id: uuid.UUID, payload: dict[str, Any]) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    ticket = await _ticket_by_id(bot, guild_id, ticket_id)
    staff = await _staff_from_payload(bot, guild_id, payload)

    try:
        await bot.claim_service.claim_ticket(ticket.channel_id, staff.id)
    except ClaimError as exc:
        raise _ticket_error(str(exc)) from exc

    updated = await _ticket_by_id(bot, guild_id, ticket_id)
    await _audit(bot, guild_id, "Ticket assumido pelo painel web", updated, {"staff": staff.display_name})
    bot.log_service.record_background(
        guild_id=guild_id,
        action=LogAction.CLAIM,
        actor_discord_id=None,
        staff_id=staff.id,
        ticket_id=updated.id,
        category_snapshot=updated.category.value,
        message=f"Painel web atribuiu o ticket para {staff.display_name}.",
    )
    await _notify_channel(_channel(guild, updated), f"🖐️ Ticket assumido por **{staff.display_name}** via painel web.")
    await _after_ticket_change(bot, guild_id)
    return {"ok": True, "message": "Ticket assumido.", "status": _status_label(updated)}


@router.post("/guild/{guild_id}/tickets/{ticket_id}/unclaim")
async def unclaim_ticket(request: Request, guild_id: int, ticket_id: uuid.UUID) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    ticket = await _ticket_by_id(bot, guild_id, ticket_id)
    if ticket.claimed_by_staff_id is None:
        raise _ticket_error("Este ticket nao esta assumido.")
    staff = await bot.staff_service.get_by_id(ticket.claimed_by_staff_id)
    if staff is None:
        raise _ticket_error("Staff responsavel nao foi encontrado.")

    try:
        await bot.claim_service.unclaim_ticket(ticket.channel_id, staff.id)
    except ClaimError as exc:
        raise _ticket_error(str(exc)) from exc

    updated = await _ticket_by_id(bot, guild_id, ticket_id)
    await _audit(bot, guild_id, "Ticket liberado pelo painel web", updated, {"staff": staff.display_name})
    bot.log_service.record_background(
        guild_id=guild_id,
        action=LogAction.UNCLAIM,
        actor_discord_id=None,
        staff_id=staff.id,
        ticket_id=updated.id,
        category_snapshot=updated.category.value,
        message=f"Painel web liberou o ticket de {staff.display_name}.",
    )
    await _notify_channel(_channel(guild, updated), f"🖐️ Ticket liberado por **Painel web**.")
    await _after_ticket_change(bot, guild_id)
    return {"ok": True, "message": "Ticket liberado.", "status": _status_label(updated)}


@router.post("/guild/{guild_id}/tickets/{ticket_id}/close")
async def close_ticket(request: Request, guild_id: int, ticket_id: uuid.UUID) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    ticket = await _ticket_by_id(bot, guild_id, ticket_id)
    if ticket.claimed_by_staff_id is None:
        raise _ticket_error("Assuma o ticket antes de fechar.")
    staff = await bot.staff_service.get_by_id(ticket.claimed_by_staff_id)
    closed_by_discord_id = staff.discord_user_id if staff is not None else 0

    try:
        result = await bot.ticket_service.close_ticket(ticket.channel_id, closed_by_discord_id)
    except (TicketNotFoundError, TicketNotClaimedError) as exc:
        raise _ticket_error(str(exc)) from exc

    updated = result.ticket
    await _audit(bot, guild_id, "Ticket fechado pelo painel web", updated, {"staff": staff.display_name if staff else None})
    bot.log_service.record_background(
        guild_id=guild_id,
        action=LogAction.FECHAMENTO,
        actor_discord_id=None,
        ticket_id=updated.id,
        category_snapshot=updated.category.value,
        message="Painel web fechou o ticket.",
    )
    await _notify_channel(_channel(guild, updated), "🔒 Ticket fechado pelo painel web.")
    await _after_ticket_change(bot, guild_id)
    return {"ok": True, "message": "Ticket fechado.", "status": _status_label(updated)}


@router.post("/guild/{guild_id}/tickets/{ticket_id}/reopen")
async def reopen_ticket(request: Request, guild_id: int, ticket_id: uuid.UUID) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    ticket = await _ticket_by_id(bot, guild_id, ticket_id)
    try:
        updated = await bot.ticket_service.reopen_ticket(ticket.channel_id)
    except TicketNotFoundError as exc:
        raise _ticket_error(str(exc), status_code=404) from exc

    await _audit(bot, guild_id, "Ticket reaberto pelo painel web", updated)
    await _notify_channel(_channel(guild, updated), "🔓 Ticket reaberto pelo painel web.")
    await _after_ticket_change(bot, guild_id)
    return {"ok": True, "message": "Ticket reaberto.", "status": _status_label(updated)}


@router.post("/guild/{guild_id}/tickets/{ticket_id}/cancel")
async def cancel_ticket(request: Request, guild_id: int, ticket_id: uuid.UUID) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    ticket = await _ticket_by_id(bot, guild_id, ticket_id)
    try:
        updated = await bot.ticket_service.cancel_ticket(ticket.channel_id)
    except TicketNotFoundError as exc:
        raise _ticket_error(str(exc), status_code=404) from exc

    await _audit(bot, guild_id, "Ticket cancelado pelo painel web", updated)
    await _notify_channel(_channel(guild, updated), "🚫 Ticket cancelado pelo painel web.")
    await _after_ticket_change(bot, guild_id)
    return {"ok": True, "message": "Ticket cancelado.", "status": _status_label(updated)}
