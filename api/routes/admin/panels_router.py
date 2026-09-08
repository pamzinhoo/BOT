from __future__ import annotations

import uuid
from typing import Any, Literal

import discord
from fastapi import APIRouter, Depends, HTTPException, Request

from api.routes.admin.security import require_local_admin
from database.models.audit_log import AuditLogCategory
from database.repositories.guild_settings_repository import GuildSettingsRepository
from database.repositories.monetization_settings_repository import MonetizationSettingsRepository
from services.ticket_panel_service import TicketPanelError

router = APIRouter(
    prefix="/admin/api",
    tags=["admin-panels"],
    dependencies=[Depends(require_local_admin)],
)

_DASHBOARD_ACTOR = "Painel web"
PanelStatus = Literal["not_published", "ok", "missing_channel", "missing_message", "error"]


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
        detail={"error": {"code": "INVALID_PANEL", "message": message, "field": field}},
    )


def _text_channel(guild: discord.Guild, raw: Any) -> discord.TextChannel:
    try:
        channel_id = int(raw)
    except (TypeError, ValueError) as exc:
        raise _payload_error("Canal invalido.", "channel_id") from exc
    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        raise _payload_error("Escolha um canal de texto existente neste servidor.", "channel_id")
    return channel


def _channel_name(bot: Any, channel_id: int | None) -> str | None:
    if channel_id is None:
        return None
    channel = bot.get_channel(channel_id)
    return getattr(channel, "name", None)


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


async def _serialize_ticket_panel(bot: Any, panel: Any) -> dict[str, Any]:
    return {
        "id": str(panel.id),
        "kind": "ticket_panel",
        "name": panel.name,
        "key": panel.key,
        "enabled": bool(panel.enabled),
        "published": panel.channel_id is not None and panel.message_id is not None,
        "channel_id": str(panel.channel_id) if panel.channel_id is not None else None,
        "channel_name": _channel_name(bot, panel.channel_id),
        "message_id": str(panel.message_id) if panel.message_id is not None else None,
        "status": await _message_status(bot, panel.channel_id, panel.message_id),
        "show_button": bool(panel.show_button),
    }


async def _serialize_group(bot: Any, group: Any) -> dict[str, Any]:
    return {
        "id": str(group.id),
        "kind": "ticket_group",
        "name": group.name,
        "panel_count": len(group.panel_ids or []),
        "published": group.channel_id is not None and group.message_id is not None,
        "channel_id": str(group.channel_id) if group.channel_id is not None else None,
        "channel_name": _channel_name(bot, group.channel_id),
        "message_id": str(group.message_id) if group.message_id is not None else None,
        "status": await _message_status(bot, group.channel_id, group.message_id),
    }


async def _fixed_panels(bot: Any, guild_id: int) -> list[dict[str, Any]]:
    async with bot.database.session() as session:
        guild_settings = await GuildSettingsRepository(session).get_by_guild_id(guild_id)
        monetization = await MonetizationSettingsRepository(session).get_by_guild_id(guild_id)

    ranking_channel_id = guild_settings.ranking_channel_id if guild_settings is not None else None
    ranking_message_id = guild_settings.ranking_message_id if guild_settings is not None else None
    shop_channel_id = monetization.shop_channel_id if monetization is not None else None
    shop_message_id = monetization.shop_message_id if monetization is not None else None

    return [
        {
            "id": "ranking",
            "kind": "ranking",
            "name": "Ranking",
            "description": "Painel fixo do ranking da staff.",
            "published": ranking_channel_id is not None and ranking_message_id is not None,
            "channel_id": str(ranking_channel_id) if ranking_channel_id is not None else None,
            "channel_name": _channel_name(bot, ranking_channel_id),
            "message_id": str(ranking_message_id) if ranking_message_id is not None else None,
            "status": await _message_status(bot, ranking_channel_id, ranking_message_id),
        },
        {
            "id": "shop",
            "kind": "shop",
            "name": "Loja / Compras",
            "description": "Painel fixo da loja, planos e DLCs pagas.",
            "published": shop_channel_id is not None and shop_message_id is not None,
            "channel_id": str(shop_channel_id) if shop_channel_id is not None else None,
            "channel_name": _channel_name(bot, shop_channel_id),
            "message_id": str(shop_message_id) if shop_message_id is not None else None,
            "status": await _message_status(bot, shop_channel_id, shop_message_id),
        },
    ]


async def _panel_payload(bot: Any, guild_id: int) -> dict[str, Any]:
    ticket_panels = await bot.ticket_panel_service.list_panels(guild_id)
    groups = await bot.ticket_panel_service.list_groups(guild_id)
    return {
        "guild_id": str(guild_id),
        "ticket_panels": [await _serialize_ticket_panel(bot, panel) for panel in ticket_panels],
        "groups": [await _serialize_group(bot, group) for group in groups],
        "fixed": await _fixed_panels(bot, guild_id),
    }


@router.get("/guild/{guild_id}/panels")
async def list_panels(request: Request, guild_id: int) -> dict[str, Any]:
    bot = _bot(request)
    _guild(bot, guild_id)
    return await _panel_payload(bot, guild_id)


@router.post("/guild/{guild_id}/panels/ticket/{panel_id}/publish")
async def publish_ticket_panel(
    request: Request, guild_id: int, panel_id: uuid.UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    channel = _text_channel(guild, payload.get("channel_id"))
    try:
        panel = await bot.ticket_panel_service.publish_panel(panel_id, channel)
    except TicketPanelError as exc:
        raise _payload_error(str(exc)) from exc
    await _record(bot, guild_id, "PAINEL_TICKET_PUBLICADO_WEB", panel_id=str(panel.id), channel_id=channel.id)
    return {"item": await _serialize_ticket_panel(bot, panel)}


@router.post("/guild/{guild_id}/panels/ticket/{panel_id}/refresh")
async def refresh_ticket_panel(request: Request, guild_id: int, panel_id: uuid.UUID) -> dict[str, Any]:
    bot = _bot(request)
    _guild(bot, guild_id)
    panel = await bot.ticket_panel_service.refresh_panel(panel_id)
    if panel is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "PANEL_NOT_FOUND", "message": "Painel nao encontrado."}})
    await _record(bot, guild_id, "PAINEL_TICKET_ATUALIZADO_WEB", panel_id=str(panel.id))
    return {"item": await _serialize_ticket_panel(bot, panel)}


@router.post("/guild/{guild_id}/panels/ticket/{panel_id}/unpublish")
async def unpublish_ticket_panel(request: Request, guild_id: int, panel_id: uuid.UUID) -> dict[str, Any]:
    bot = _bot(request)
    _guild(bot, guild_id)
    try:
        panel = await bot.ticket_panel_service.unpublish_panel(panel_id)
    except TicketPanelError as exc:
        raise _payload_error(str(exc)) from exc
    await _record(bot, guild_id, "PAINEL_TICKET_REMOVIDO_WEB", panel_id=str(panel.id))
    return {"item": await _serialize_ticket_panel(bot, panel)}


@router.post("/guild/{guild_id}/panels/group/{group_id}/publish")
async def publish_ticket_group(
    request: Request, guild_id: int, group_id: uuid.UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    channel = _text_channel(guild, payload.get("channel_id"))
    try:
        group = await bot.ticket_panel_service.publish_group(group_id, channel)
    except TicketPanelError as exc:
        raise _payload_error(str(exc)) from exc
    await _record(bot, guild_id, "COMBO_TICKET_PUBLICADO_WEB", group_id=str(group.id), channel_id=channel.id)
    return {"item": await _serialize_group(bot, group)}


@router.post("/guild/{guild_id}/panels/group/{group_id}/refresh")
async def refresh_ticket_group(request: Request, guild_id: int, group_id: uuid.UUID) -> dict[str, Any]:
    bot = _bot(request)
    _guild(bot, guild_id)
    group = await bot.ticket_panel_service.refresh_group(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "GROUP_NOT_FOUND", "message": "Combo nao encontrado."}})
    await _record(bot, guild_id, "COMBO_TICKET_ATUALIZADO_WEB", group_id=str(group.id))
    return {"item": await _serialize_group(bot, group)}


@router.post("/guild/{guild_id}/panels/group/{group_id}/unpublish")
async def unpublish_ticket_group(request: Request, guild_id: int, group_id: uuid.UUID) -> dict[str, Any]:
    bot = _bot(request)
    _guild(bot, guild_id)
    try:
        group = await bot.ticket_panel_service.unpublish_group(group_id)
    except TicketPanelError as exc:
        raise _payload_error(str(exc)) from exc
    await _record(bot, guild_id, "COMBO_TICKET_REMOVIDO_WEB", group_id=str(group.id))
    return {"item": await _serialize_group(bot, group)}


@router.post("/guild/{guild_id}/panels/fixed/ranking/publish")
async def publish_ranking_panel(request: Request, guild_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    channel = _text_channel(guild, payload.get("channel_id"))
    async with bot.database.session() as session:
        settings = await GuildSettingsRepository(session).get_or_create(guild_id)
        if settings.ranking_channel_id != channel.id:
            await _delete_saved_message(bot, settings.ranking_channel_id, settings.ranking_message_id)
            settings.ranking_message_id = None
        settings.ranking_channel_id = channel.id
    ok, message = await bot.painel_service.publish_ranking(guild_id)
    if not ok:
        raise _payload_error(message)
    await _record(bot, guild_id, "PAINEL_RANKING_PUBLICADO_WEB", channel_id=channel.id)
    return await _panel_payload(bot, guild_id)


@router.post("/guild/{guild_id}/panels/fixed/ranking/refresh")
async def refresh_ranking_panel(request: Request, guild_id: int) -> dict[str, Any]:
    bot = _bot(request)
    _guild(bot, guild_id)
    ok, message = await bot.painel_service.publish_ranking(guild_id)
    if not ok:
        raise _payload_error(message)
    await _record(bot, guild_id, "PAINEL_RANKING_ATUALIZADO_WEB")
    return await _panel_payload(bot, guild_id)


@router.post("/guild/{guild_id}/panels/fixed/shop/publish")
async def publish_shop_panel(request: Request, guild_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    channel = _text_channel(guild, payload.get("channel_id"))
    async with bot.database.session() as session:
        settings = await MonetizationSettingsRepository(session).get_or_create(guild_id)
        await _delete_saved_message(bot, settings.shop_channel_id, settings.shop_message_id)
    try:
        await bot.painel_service.publish_shop_panel(guild_id, channel.id)
    except discord.HTTPException as exc:
        raise _payload_error("Nao foi possivel publicar o painel da loja nesse canal.") from exc
    await _record(bot, guild_id, "PAINEL_LOJA_PUBLICADO_WEB", channel_id=channel.id)
    return await _panel_payload(bot, guild_id)


@router.post("/guild/{guild_id}/panels/fixed/shop/refresh")
async def refresh_shop_panel(request: Request, guild_id: int) -> dict[str, Any]:
    bot = _bot(request)
    _guild(bot, guild_id)
    await bot.painel_service.refresh_shop_panel(guild_id)
    await _record(bot, guild_id, "PAINEL_LOJA_ATUALIZADO_WEB")
    return await _panel_payload(bot, guild_id)
