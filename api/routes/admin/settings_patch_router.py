from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from api.routes.admin.security import require_local_admin
from api.routes.admin.settings_router import (
    _bot,
    _clean_label,
    _coerce_value,
    _guild,
    _resolve_legacy_key,
    _serialize_value,
    _settings_bundle,
)

router = APIRouter(
    prefix="/admin/api",
    tags=["admin-settings"],
    dependencies=[Depends(require_local_admin)],
)

_DASHBOARD_ACTOR = "Painel web"


@router.patch("/guild/{guild_id}/settings")
async def update_settings(request: Request, guild_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    """Override seguro do PATCH de settings para auditoria do painel web.

    O router principal ainda possui a implementacao completa. Este endpoint fica
    registrado antes dele e evita usar actor_id=0, porque o embed de auditoria
    renderiza qualquer ID como mencao Discord (<@0>). Para acoes sem usuario
    real, o executor precisa ser apenas o nome textual do painel.
    """
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    if guild is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "GUILD_NOT_FOUND", "message": "Servidor nao encontrado."}},
        )
    raw_values = payload.get("values")
    if not isinstance(raw_values, dict):
        raise HTTPException(
            status_code=422,
            detail={"error": {"code": "INVALID_PAYLOAD", "message": "Envie um objeto values."}},
        )

    _, before, updaters = await _settings_bundle(bot, guild_id, guild)
    grouped: dict[Any, dict[str, Any]] = {}
    changes: list[tuple[str, str, Any, Any]] = []

    for raw_key, raw_value in raw_values.items():
        key = _resolve_legacy_key(str(raw_key), updaters)
        if key is None:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "code": "INVALID_SETTING",
                        "message": "Configuracao desconhecida ou ambigua.",
                        "field": str(raw_key),
                    }
                },
            )
        entry = updaters[key]
        try:
            value = _coerce_value(entry.field, raw_value, guild)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"error": {"code": "INVALID_SETTING", "message": str(exc), "field": key}},
            ) from exc
        grouped.setdefault(entry.updater, {})[entry.field.attr] = value
        serialized = _serialize_value(value)
        if before.get(key) != serialized:
            changes.append((entry.category_title, entry.field.label, before.get(key), serialized))

    for updater, values in grouped.items():
        await updater(guild_id, **values)

    for section, label, old, new in changes:
        await bot.audit_log_service.record_config_change(
            guild_id=guild_id,
            actor_id=None,
            actor_name=_DASHBOARD_ACTOR,
            config_category=section,
            config_name=_clean_label(label),
            old_value=str(old),
            new_value=str(new),
        )

    sections, values, _ = await _settings_bundle(bot, guild_id, guild)
    return {"guild_id": str(guild_id), "sections": sections, "values": values}
