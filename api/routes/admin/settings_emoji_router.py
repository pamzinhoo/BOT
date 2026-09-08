from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from api.routes.admin import settings_router as base_settings_router
from api.routes.admin.security import require_local_admin

router = APIRouter(
    prefix="/admin/api",
    tags=["admin-settings-emoji"],
    dependencies=[Depends(require_local_admin)],
)

_EMOJI_KEYS = {"avaliacoes.star_emoji", "star_emoji"}
_NAMESPACED_EMOJI_KEY = "avaliacoes.star_emoji"
_DASHBOARD_ACTOR = "Painel web"


def _force_emoji_as_text(payload: dict[str, Any]) -> dict[str, Any]:
    """Mantem compatibilidade com o /config, mas no web dashboard o emoji e livre.

    No painel Discord existe uma lista curta de emojis. No web dashboard, o
    admin precisa poder colar qualquer emoji unicode ou emoji custom do Discord.
    """
    for section in payload.get("sections", []):
        for field in section.get("fields", []):
            if field.get("key") == _NAMESPACED_EMOJI_KEY or field.get("attr") == "star_emoji":
                field["type"] = "text"
                field["options"] = []
                field["description"] = (
                    "Digite o emoji usado nas estrelas. Aceita emoji comum ou custom do Discord."
                )
    return payload


def _extract_emoji_update(values: dict[str, Any]) -> tuple[dict[str, Any], Any, bool]:
    rest: dict[str, Any] = {}
    emoji_value: Any = None
    found = False
    for key, value in values.items():
        if str(key) in _EMOJI_KEYS:
            emoji_value = value
            found = True
        else:
            rest[str(key)] = value
    return rest, emoji_value, found


@router.get("/guild/{guild_id}/settings")
async def get_settings(request: Request, guild_id: int) -> dict[str, Any]:
    payload = await base_settings_router.get_settings(request, guild_id)
    return _force_emoji_as_text(payload)


@router.patch("/guild/{guild_id}/settings")
async def update_settings(request: Request, guild_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    raw_values = payload.get("values")
    if not isinstance(raw_values, dict):
        raise HTTPException(
            status_code=422,
            detail={"error": {"code": "INVALID_PAYLOAD", "message": "Envie um objeto values."}},
        )

    rest, emoji_value, has_emoji = _extract_emoji_update(raw_values)
    if rest:
        await base_settings_router.update_settings(request, guild_id, {"values": rest})

    if has_emoji:
        bot = request.app.state.bot
        current = await bot.config_service.get_evaluation_settings(guild_id)
        before = getattr(current, "star_emoji", None)
        normalized = str(emoji_value or "").strip() or None
        await bot.config_service.update_evaluation_settings(guild_id, star_emoji=normalized)
        await bot.audit_log_service.record_config_change(
            guild_id=guild_id,
            actor_id=0,
            actor_name=_DASHBOARD_ACTOR,
            config_category="Avaliações",
            config_name="Emoji das Estrelas",
            old_value=str(before),
            new_value=str(normalized),
        )

    response = await base_settings_router.get_settings(request, guild_id)
    return _force_emoji_as_text(response)
