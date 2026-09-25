from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import discord
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from api.routes.admin.security import require_local_admin
from cogs.event_timers import finish_event_timer, publish_event_timer
from database.models.audit_log import AuditLogCategory
from database.models.event_timer import EventTimer
from services.event_timer_service import EventTimerValidationError

router = APIRouter(
    prefix="/admin/api",
    tags=["admin-event-timers"],
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


def _channel(guild: discord.Guild, channel_id: int) -> discord.TextChannel:
    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        raise HTTPException(
            status_code=422,
            detail={
                "error": {"code": "INVALID_CHANNEL", "message": "Escolha um canal de texto valido."}
            },
        )
    return channel


def _serialize(guild: discord.Guild, event: EventTimer) -> dict[str, Any]:
    channel = guild.get_channel(event.channel_id)
    status = event.status.value if hasattr(event.status, "value") else str(event.status)
    return {
        "id": str(event.id),
        "title": event.title,
        "description": event.description,
        "status": status,
        "channel_id": str(event.channel_id),
        "channel_name": getattr(channel, "name", None),
        "channel_missing": channel is None,
        "message_id": str(event.message_id) if event.message_id else None,
        "creator_id": str(event.creator_id),
        "repeat_interval_seconds": event.repeat_interval_seconds,
        "mention_everyone": event.mention_everyone,
        "ends_at": event.ends_at.isoformat(),
        "next_announcement_at": (
            event.next_announcement_at.isoformat() if event.next_announcement_at else None
        ),
        "last_announcement_at": (
            event.last_announcement_at.isoformat() if event.last_announcement_at else None
        ),
        "finished_at": event.finished_at.isoformat() if event.finished_at else None,
        "last_error": event.last_error,
        "has_image": bool(event.image_storage_path),
        "image_filename": event.image_filename,
        "image_size": event.image_size,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def _parse_end(
    end_mode: str, duration_amount: int | None, duration_unit: str | None, ends_at: str | None
) -> datetime:
    if end_mode == "date":
        if not ends_at:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": {"code": "INVALID_END", "message": "Informe a data de encerramento."}
                },
            )
        try:
            parsed = datetime.fromisoformat(ends_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": {"code": "INVALID_END", "message": "Data de encerramento invalida."}
                },
            ) from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    amount = int(duration_amount or 0)
    seconds = {"minutes": 60, "hours": 3600, "days": 86400}.get(duration_unit or "hours")
    if amount < 1 or seconds is None:
        raise HTTPException(
            status_code=422,
            detail={"error": {"code": "INVALID_DURATION", "message": "Duracao invalida."}},
        )
    return datetime.now(UTC) + timedelta(seconds=amount * seconds)


@router.get("/guild/{guild_id}/event-timers")
async def list_event_timers(request: Request, guild_id: int) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    items = await bot.event_timer_service.list_by_guild(guild_id)
    return {"guild_id": str(guild_id), "items": [_serialize(guild, item) for item in items]}


@router.post("/guild/{guild_id}/event-timers")
async def create_event_timer(
    request: Request,
    guild_id: int,
    title: str = Form(...),
    description: str = Form(""),
    channel_id: int = Form(...),
    repeat_interval_seconds: int = Form(...),
    end_mode: str = Form("duration"),
    duration_amount: int | None = Form(None),
    duration_unit: str | None = Form(None),
    ends_at: str | None = Form(None),
    mention_everyone: bool = Form(True),
    image: UploadFile | None = File(None),
) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    channel = _channel(guild, channel_id)
    image_bytes = await image.read() if image else None
    try:
        event = await bot.event_timer_service.create(
            guild_id=guild_id,
            creator_id=0,
            channel_id=channel.id,
            title=title,
            description=description,
            ends_at=_parse_end(end_mode, duration_amount, duration_unit, ends_at),
            repeat_interval_seconds=repeat_interval_seconds,
            mention_everyone=mention_everyone,
            image_bytes=image_bytes,
            image_filename=image.filename if image else None,
            image_content_type=image.content_type if image else None,
        )
    except EventTimerValidationError as exc:
        raise HTTPException(
            status_code=422, detail={"error": {"code": "INVALID_EVENT_TIMER", "message": str(exc)}}
        ) from exc

    try:
        message_id = await publish_event_timer(bot, event)
        await bot.event_timer_service.mark_announced(event.id, message_id, datetime.now(UTC))
    except discord.Forbidden as exc:
        await bot.event_timer_service.finish(event.id, canceled=True)
        raise HTTPException(
            status_code=403,
            detail={
                "error": {
                    "code": "DISCORD_FORBIDDEN",
                    "message": "Sem permissao para publicar ou mencionar @everyone nesse canal.",
                }
            },
        ) from exc
    except Exception as exc:
        await bot.event_timer_service.mark_error(event.id, str(exc))
        raise HTTPException(
            status_code=502,
            detail={
                "error": {
                    "code": "EVENT_PUBLISH_FAILED",
                    "message": "Falha ao publicar o evento no Discord.",
                }
            },
        ) from exc
    await bot.audit_log_service.record(
        guild_id=guild_id,
        category=AuditLogCategory.SERVER_CONFIG,
        action="EVENT_TIMER_CREATED",
        executor_name=_DASHBOARD_ACTOR,
        details={"event_id": str(event.id), "title": event.title, "channel_id": channel.id},
    )
    fresh = await bot.event_timer_service.get(event.id) or event
    return {"item": _serialize(guild, fresh)}


async def _get_owned(bot: Any, guild_id: int, event_id: uuid.UUID) -> EventTimer:
    event = await bot.event_timer_service.get(event_id)
    if event is None or event.guild_id != guild_id:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {"code": "EVENT_TIMER_NOT_FOUND", "message": "Cronometro nao encontrado."}
            },
        )
    return event


@router.post("/guild/{guild_id}/event-timers/{event_id}/pause")
async def pause_event_timer(request: Request, guild_id: int, event_id: uuid.UUID) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    await _get_owned(bot, guild_id, event_id)
    event = await bot.event_timer_service.pause(event_id)
    if event is None:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "INVALID_STATE",
                    "message": "Somente evento ativo pode ser pausado.",
                }
            },
        )
    return {"item": _serialize(guild, event)}


@router.post("/guild/{guild_id}/event-timers/{event_id}/resume")
async def resume_event_timer(
    request: Request, guild_id: int, event_id: uuid.UUID
) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    await _get_owned(bot, guild_id, event_id)
    event = await bot.event_timer_service.resume(event_id)
    if event is None:
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "INVALID_STATE", "message": "Evento nao pode ser retomado."}},
        )
    return {"item": _serialize(guild, event)}


@router.post("/guild/{guild_id}/event-timers/{event_id}/resend")
async def resend_event_timer(
    request: Request, guild_id: int, event_id: uuid.UUID
) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    event = await _get_owned(bot, guild_id, event_id)
    if event.status.value != "ACTIVE":
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "INVALID_STATE",
                    "message": "Somente evento ativo pode ser reenviado.",
                }
            },
        )
    message_id = await publish_event_timer(bot, event)
    await bot.event_timer_service.mark_announced(event.id, message_id, datetime.now(UTC))
    fresh = await bot.event_timer_service.get(event.id) or event
    return {"item": _serialize(guild, fresh)}


@router.post("/guild/{guild_id}/event-timers/{event_id}/cancel")
async def cancel_event_timer(
    request: Request, guild_id: int, event_id: uuid.UUID
) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    event = await _get_owned(bot, guild_id, event_id)
    await finish_event_timer(bot, event, canceled=True)
    fresh = await bot.event_timer_service.get(event.id) or event
    return {"item": _serialize(guild, fresh)}
