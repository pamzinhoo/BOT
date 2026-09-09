from __future__ import annotations

from typing import Any, Literal

import discord
from fastapi import APIRouter, Depends, HTTPException, Request

from api.routes.admin.security import require_local_admin
from database.models.audit_log import AuditLogCategory
from database.repositories.monetization_settings_repository import MonetizationSettingsRepository

router = APIRouter(
    prefix="/admin/api",
    tags=["admin-monetization-settings"],
    dependencies=[Depends(require_local_admin)],
)

_DASHBOARD_ACTOR = "Painel web"
PanelStatus = Literal["not_published", "ok", "missing_channel", "missing_message", "error"]


_CHANNEL_FIELDS = {
    "shop_channel_id": "Canal da loja",
    "approval_channel_id": "Canal de aprovação manual",
    "log_channel_id": "Canal de logs da monetização",
    "dlc_announcement_channel_id": "Canal de anúncios de DLC",
}


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
        detail={"error": {"code": "INVALID_MONETIZATION_SETTINGS", "message": message, "field": field}},
    )


def _channel_id(guild: discord.Guild, raw: Any, field: str) -> int | None:
    if raw in (None, ""):
        return None
    try:
        channel_id = int(raw)
    except (TypeError, ValueError) as exc:
        raise _payload_error("Canal invalido.", field) from exc
    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        raise _payload_error("Escolha um canal de texto existente neste servidor.", field)
    return channel_id


def _channel_payload(bot: Any, channel_id: int | None) -> dict[str, Any]:
    if channel_id is None:
        return {"id": None, "name": None, "missing": False}
    channel = bot.get_channel(channel_id)
    return {
        "id": str(channel_id),
        "name": getattr(channel, "name", None),
        "missing": channel is None,
    }


async def _message_status(bot: Any, channel_id: int | None, message_id: int | None) -> PanelStatus:
    if channel_id is None or message_id is None:
        return "not_published"
    channel = bot.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return "missing_channel"
    try:
        await channel.fetch_message(message_id)
    except discord.NotFound:
        return "missing_message"
    except discord.HTTPException:
        return "error"
    return "ok"


async def _delete_saved_message(bot: Any, channel_id: int | None, message_id: int | None) -> None:
    if channel_id is None or message_id is None:
        return
    channel = bot.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        message = await channel.fetch_message(message_id)
        await message.delete()
    except discord.HTTPException:
        return


async def _record(bot: Any, guild_id: int, action: str, **details: object) -> None:
    await bot.audit_log_service.record(
        guild_id=guild_id,
        category=AuditLogCategory.SERVER_CONFIG,
        action=action,
        executor_name=_DASHBOARD_ACTOR,
        details=details,
    )


async def _payload(bot: Any, guild_id: int) -> dict[str, Any]:
    async with bot.database.session() as session:
        settings = await MonetizationSettingsRepository(session).get_or_create(guild_id)
        values = {
            "shop_channel_id": str(settings.shop_channel_id) if settings.shop_channel_id else None,
            "approval_channel_id": str(settings.approval_channel_id) if settings.approval_channel_id else None,
            "log_channel_id": str(settings.log_channel_id) if settings.log_channel_id else None,
            "dlc_announcement_channel_id": str(settings.dlc_announcement_channel_id) if settings.dlc_announcement_channel_id else None,
            "shop_message_id": str(settings.shop_message_id) if settings.shop_message_id else None,
            "updated_at": settings.updated_at.isoformat() if settings.updated_at else None,
        }
        raw_shop_channel_id = settings.shop_channel_id
        raw_shop_message_id = settings.shop_message_id

    app_settings = bot.settings
    return {
        "guild_id": str(guild_id),
        "values": values,
        "channels": {
            key: _channel_payload(bot, int(value)) if value else {"id": None, "name": None, "missing": False}
            for key, value in values.items()
            if key.endswith("_channel_id")
        },
        "shop_panel": {
            "published": raw_shop_channel_id is not None and raw_shop_message_id is not None,
            "channel_id": str(raw_shop_channel_id) if raw_shop_channel_id else None,
            "message_id": str(raw_shop_message_id) if raw_shop_message_id else None,
            "status": await _message_status(bot, raw_shop_channel_id, raw_shop_message_id),
        },
        "gateway": {
            "payment_mode": app_settings.payment_mode,
            "environment": app_settings.environment,
            "webhook_enabled": app_settings.webhook_enabled,
            "public_base_url_configured": bool(app_settings.public_base_url),
            "mercadopago_access_token_configured": bool(app_settings.mercadopago_access_token),
            "mercadopago_public_key_configured": bool(app_settings.mercadopago_public_key),
            "mercadopago_webhook_secret_configured": bool(app_settings.mercadopago_webhook_secret),
            "readonly_env": True,
        },
        "security_notes": [
            "Fase 3.4: configura apenas canais e publicação da loja.",
            "Nao altera registros financeiros, assinaturas, licencas, produtos ou cargos do Discord.",
            "Tokens, chaves e modo Mercado Pago continuam somente no .env, sem aparecer no painel.",
            "Publicar loja usa PainelService e nao gera QR Code PIX.",
        ],
    }


@router.get("/guild/{guild_id}/monetization/settings")
async def get_monetization_settings(request: Request, guild_id: int) -> dict[str, Any]:
    bot = _bot(request)
    _guild(bot, guild_id)
    return await _payload(bot, guild_id)


@router.patch("/guild/{guild_id}/monetization/settings")
async def update_monetization_settings(request: Request, guild_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    values = payload.get("values")
    if not isinstance(values, dict):
        raise _payload_error("Envie um objeto values.")

    updates: dict[str, int | None] = {}
    for field in _CHANNEL_FIELDS:
        if field in values:
            updates[field] = _channel_id(guild, values.get(field), field)
    if not updates:
        return await _payload(bot, guild_id)

    changes: list[tuple[str, str | None, str | None]] = []
    async with bot.database.session() as session:
        settings = await MonetizationSettingsRepository(session).get_or_create(guild_id)
        for field, new_value in updates.items():
            old_value = getattr(settings, field)
            if old_value != new_value:
                setattr(settings, field, new_value)
                changes.append((field, str(old_value) if old_value else None, str(new_value) if new_value else None))
                if field == "shop_channel_id":
                    settings.shop_message_id = None

    for field, old, new in changes:
        await bot.audit_log_service.record_config_change(
            guild_id=guild_id,
            actor_id=0,
            actor_name=_DASHBOARD_ACTOR,
            config_category="Monetização",
            config_name=_CHANNEL_FIELDS[field],
            old_value=str(old),
            new_value=str(new),
        )
    return await _payload(bot, guild_id)


@router.post("/guild/{guild_id}/monetization/settings/shop/publish")
async def publish_shop_from_monetization_settings(request: Request, guild_id: int) -> dict[str, Any]:
    bot = _bot(request)
    _guild(bot, guild_id)
    async with bot.database.session() as session:
        settings = await MonetizationSettingsRepository(session).get_or_create(guild_id)
        if settings.shop_channel_id is None:
            raise _payload_error("Configure o canal da loja antes de publicar.", "shop_channel_id")
        channel_id = settings.shop_channel_id
        old_channel_id = settings.shop_channel_id
        old_message_id = settings.shop_message_id
        settings.shop_message_id = None
    await _delete_saved_message(bot, old_channel_id, old_message_id)
    try:
        await bot.painel_service.publish_shop_panel(guild_id, channel_id)
    except discord.HTTPException as exc:
        raise _payload_error("Nao foi possivel publicar o painel da loja nesse canal.") from exc
    await _record(bot, guild_id, "PAINEL_LOJA_PUBLICADO_MONETIZACAO_WEB", channel_id=channel_id)
    return await _payload(bot, guild_id)


@router.post("/guild/{guild_id}/monetization/settings/shop/refresh")
async def refresh_shop_from_monetization_settings(request: Request, guild_id: int) -> dict[str, Any]:
    bot = _bot(request)
    _guild(bot, guild_id)
    await bot.painel_service.refresh_shop_panel(guild_id)
    await _record(bot, guild_id, "PAINEL_LOJA_ATUALIZADO_MONETIZACAO_WEB")
    return await _payload(bot, guild_id)
