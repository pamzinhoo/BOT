from __future__ import annotations

from typing import Any

import discord
from fastapi import APIRouter, Depends, HTTPException, Request

from api.routes.admin.security import require_local_admin
from database.models.audit_log import AuditLogCategory
from database.models.social_notification import SocialNotification
from services.social_notification_service import SocialNotificationValidationError

router = APIRouter(
    prefix="/admin/api",
    tags=["admin-social-notifications"],
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


def _channel(guild: discord.Guild, raw: Any) -> discord.TextChannel:
    try:
        channel_id = int(raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "INVALID_CHANNEL",
                    "message": "Canal invalido.",
                    "field": "channel_id",
                }
            },
        ) from exc
    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "INVALID_CHANNEL",
                    "message": "Escolha um canal de texto existente neste servidor.",
                    "field": "channel_id",
                }
            },
        )
    return channel


def _serialize(item: SocialNotification, guild: discord.Guild) -> dict[str, Any]:
    channel = guild.get_channel(item.channel_id)
    return {
        "id": str(item.id),
        "platform": item.platform.value,
        "url": item.url,
        "message_template": item.message_template,
        "mention_everyone": item.mention_everyone,
        "status": item.status.value,
        "channel_id": str(item.channel_id),
        "channel_name": getattr(channel, "name", None),
        "channel_missing": channel is None,
        "message_id": str(item.message_id) if item.message_id else None,
        "error_message": item.error_message,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


@router.get("/guild/{guild_id}/social-notifications")
async def list_social_notifications(request: Request, guild_id: int) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    items = await bot.social_notification_service.list_by_guild(guild_id)
    return {"guild_id": str(guild_id), "items": [_serialize(item, guild) for item in items]}


@router.post("/guild/{guild_id}/social-notifications")
async def create_social_notification(
    request: Request, guild_id: int, payload: dict[str, Any]
) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    channel = _channel(guild, payload.get("channel_id"))
    url = str(payload.get("url") or "")
    message_template = str(payload.get("message") or payload.get("message_template") or "")
    mention_everyone = bool(payload.get("mention_everyone", False))

    if not message_template.strip():
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "INVALID_MESSAGE",
                    "message": "Informe uma mensagem.",
                    "field": "message",
                }
            },
        )

    try:
        item = await bot.social_notification_service.send_manual(
            guild_id=guild_id,
            creator_id=0,
            channel_id=channel.id,
            url=url,
            message_template=message_template,
            mention_everyone=mention_everyone,
        )
    except SocialNotificationValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": {"code": "SOCIAL_NOTIFICATION_INVALID", "message": str(exc)}},
        ) from exc

    bot.audit_log_service.record_background(
        guild_id=guild_id,
        category=AuditLogCategory.SERVER_CONFIG,
        action="NOTIFICACAO_SOCIAL_ENVIADA_PAINEL_WEB",
        executor_name=_DASHBOARD_ACTOR,
        details={
            "notification_id": str(item.id),
            "platform": item.platform.value,
            "channel_id": channel.id,
            "message_id": item.message_id,
        },
    )
    return {"item": _serialize(item, guild)}


@router.post("/guild/{guild_id}/social-notifications/preview")
async def preview_social_notification(
    request: Request, guild_id: int, payload: dict[str, Any]
) -> dict[str, str]:
    _guild(_bot(request), guild_id)
    url = str(payload.get("url") or "")
    message_template = str(payload.get("message") or payload.get("message_template") or "")
    try:
        service = _bot(request).social_notification_service
        clean_url = service.validate_url(url)
        from services.social_notification_service import detect_platform, render_message

        return {
            "platform": detect_platform(clean_url).value,
            "message": render_message(message_template, clean_url),
            "url": clean_url,
        }
    except SocialNotificationValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": {"code": "SOCIAL_NOTIFICATION_INVALID", "message": str(exc)}},
        ) from exc
