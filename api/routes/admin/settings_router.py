from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import discord
from fastapi import APIRouter, Depends, HTTPException, Request

from api.routes.admin.security import require_local_admin
from views.master_config_view import iter_categories
from views.settings_panel import FieldKind, SettingsField

router = APIRouter(
    prefix="/admin/api",
    tags=["admin-settings"],
    dependencies=[Depends(require_local_admin)],
)

_CATEGORY_DESCRIPTIONS = {
    "tickets": "Comportamento, canais, limites e automacoes do atendimento.",
    "cargos": "Cargos base usados pelas regras do bot.",
    "permissoes": "Cargos autorizados para cada acao administrativa.",
    "dashboard": "Publicacao e atualizacao do painel de ranking/status.",
    "ranking": "Criterio, periodo e publicacao do ranking.",
    "avaliacoes": "Coleta, destino e mensagens de avaliacao.",
    "antispam": "Limites de flood, janela de analise e acoes automaticas.",
    "alertas": "Canais usados para avisos operacionais.",
    "moderacao": "Prazos, canais e regras de punicoes e recursos.",
    "boost": "Beneficios e mensagens ligadas a boosts.",
    "verificacao": "Fluxo de verificacao, captcha, cargo e mensagens.",
    "parcerias": "Cargos, canais e regras do fluxo de parceria.",
}

_FIELD_DESCRIPTIONS = {
    "allow_multiple_tickets": "Permite mais de um ticket aberto pelo mesmo usuario.",
    "auto_close_enabled": "Liga o fechamento automatico de tickets inativos.",
    "blacklist_channel_id": "Canal usado para alertas de blacklist e spam.",
    "channel_id": "Canal onde este modulo publica ou atualiza mensagens.",
    "cross_channel_threshold": "Quantidade de canais diferentes usada para detectar spam cruzado.",
    "dashboard_channel_id": "Canal onde o dashboard publico do bot e publicado.",
    "default_action": "Acao aplicada quando o detector encontra spam.",
    "default_period": "Periodo padrao usado nas consultas de ranking.",
    "delete_delay_seconds": "Tempo de espera antes de apagar o canal do ticket fechado.",
    "dm_button_label": "Texto do botao enviado por DM.",
    "dm_embed_description": "Descricao do embed enviado por DM.",
    "dm_embed_title": "Titulo do embed enviado por DM.",
    "dm_prompt_text": "Texto que acompanha o pedido de avaliacao por DM.",
    "dm_thanks_message": "Mensagem exibida depois que o usuario avalia.",
    "enabled": "Liga ou desliga este modulo.",
    "evaluation_method": "Define se a avaliacao acontece no ticket, por DM ou nos dois.",
    "evaluations_channel_id": "Canal onde as avaliacoes ficam registradas.",
    "flood_threshold": "Quantidade de mensagens usada para detectar flood.",
    "ignore_staff": "Ignora membros da staff nas regras deste modulo.",
    "inactive_after_minutes": "Tempo sem atividade antes de considerar o ticket inativo.",
    "log_channel_id": "Canal usado para registrar logs deste modulo.",
    "max_tickets_per_user": "Limite de tickets abertos por usuario.",
    "min_comment_rating": "Nota a partir da qual comentario pode ser obrigatorio.",
    "ranking_channel_id": "Canal onde o ranking e publicado.",
    "show_chart": "Exibe ou oculta grafico no painel.",
    "star_emoji": "Emoji usado para representar as estrelas da avaliacao.",
    "ticket_alert_channel_id": "Canal avisado quando um ticket novo abre.",
    "ticket_category_id": "Categoria onde novos tickets serao criados.",
    "top_count": "Quantidade de pessoas exibidas no topo do painel.",
    "transcript_channel_id": "Canal onde as transcricoes de tickets sao enviadas.",
    "update_interval_minutes": "Intervalo entre atualizacoes automaticas.",
    "verified_role_id": "Cargo concedido ao usuario verificado e usado pelas DLCs gratuitas.",
    "window_seconds": "Janela de tempo analisada pelo anti-spam.",
}

_DURATION_UNITS = {
    "seconds": {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400},
    "minutes": {"seconds": 1 / 60, "minutes": 1, "hours": 60, "days": 1440},
}

_DURATION_LABELS = {
    "seconds": "segundos",
    "minutes": "minutos",
    "hours": "horas",
    "days": "dias",
}


@dataclass(frozen=True)
class _UpdaterEntry:
    category_key: str
    category_title: str
    field: SettingsField
    updater: Any

    @property
    def namespaced_key(self) -> str:
        return f"{self.category_key}.{self.field.attr}"


def _bot(request: Request):
    return request.app.state.bot


def _clean_label(value: str) -> str:
    value = re.sub(r"^[^\w]+", "", value, flags=re.UNICODE).strip()
    return value.replace("  ", " ")


def _field_type(field: SettingsField) -> str:
    if field.kind == FieldKind.CHOICE and not field.choices:
        # Alguns campos antigos foram marcados como CHOICE, mas nao possuem
        # opcoes fixas. No dashboard eles precisam virar texto livre; senao a UI
        # mostra um select vazio, como acontecia com avaliacoes.star_emoji.
        return "text"
    return {
        FieldKind.CHANNEL: "channel",
        FieldKind.ROLE: "role",
        FieldKind.ROLE_MULTI: "role_multi",
        FieldKind.NUMBER: "number",
        FieldKind.BOOL: "bool",
        FieldKind.CHOICE: "choice",
        FieldKind.TEXT: "text",
    }[field.kind]


def _unit_for(field: SettingsField) -> str | None:
    attr = field.attr.lower()
    label = field.label.lower()
    if attr.endswith("_seconds") or "segundo" in label or "(s)" in label:
        return "seconds"
    if attr.endswith("_minutes") or "min" in label:
        return "minutes"
    return None


def _model_name(field: SettingsField) -> str | None:
    model = getattr(field, "model", object)
    if model is object:
        return None
    return getattr(model, "__name__", None)


def _reference_state(guild: discord.Guild, field: SettingsField, raw: Any) -> dict[str, Any]:
    if raw in (None, "", []):
        return {"status": "ok", "message": "Nao definido; usa padrao do bot quando existir."}
    if field.kind == FieldKind.CHANNEL:
        channel = guild.get_channel(int(raw))
        if channel is None:
            return {
                "status": "error",
                "message": "Canal salvo nao existe mais neste servidor. Escolha outro antes de depender desta config.",
                "missing_reference": True,
            }
        allowed = field.channel_types or []
        if allowed and getattr(channel, "type", None) not in allowed:
            return {
                "status": "warning",
                "message": "Canal existe, mas o tipo nao corresponde ao esperado para este campo.",
                "missing_reference": False,
            }
        return {"status": "ok", "message": f"Canal encontrado: #{getattr(channel, 'name', raw)}."}
    if field.kind == FieldKind.ROLE:
        role = guild.get_role(int(raw))
        if role is None:
            return {
                "status": "error",
                "message": "Cargo salvo nao existe mais neste servidor. Escolha outro antes de depender desta config.",
                "missing_reference": True,
            }
        if role.is_default():
            return {
                "status": "warning",
                "message": "O cargo @everyone nao deve ser usado como cargo operacional.",
                "missing_reference": False,
            }
        return {"status": "ok", "message": f"Cargo encontrado: {role.name}."}
    if field.kind == FieldKind.ROLE_MULTI:
        ids = [int(item) for item in (raw or [])]
        missing = [str(role_id) for role_id in ids if guild.get_role(role_id) is None]
        if missing:
            return {
                "status": "error",
                "message": f"{len(missing)} cargo(s) salvo(s) nao existem mais neste servidor.",
                "missing_reference": True,
            }
        return {"status": "ok", "message": "Todos os cargos foram encontrados." if ids else "Lista vazia; usa padrao do bot."}
    return {"status": "ok", "message": "Valor pronto para uso pelo bot."}


def _validate_reference(guild: discord.Guild, field: SettingsField, value: Any) -> None:
    if value in (None, "", []):
        return
    if field.kind == FieldKind.CHANNEL:
        channel = guild.get_channel(int(value))
        if channel is None:
            raise ValueError("Canal nao encontrado neste servidor.")
        allowed = field.channel_types or []
        if allowed and getattr(channel, "type", None) not in allowed:
            raise ValueError("Tipo de canal invalido para esta configuracao.")
    elif field.kind == FieldKind.ROLE:
        role = guild.get_role(int(value))
        if role is None or role.is_default():
            raise ValueError("Cargo nao encontrado ou invalido neste servidor.")
    elif field.kind == FieldKind.ROLE_MULTI:
        role_ids = [int(item) for item in value]
        invalid = [role_id for role_id in role_ids if guild.get_role(role_id) is None]
        if invalid:
            raise ValueError("Um ou mais cargos nao existem neste servidor.")


def _setting_definition(category_key: str, category_title: str, field: SettingsField, raw_value: Any, guild: discord.Guild) -> dict[str, Any]:
    unit = _unit_for(field)
    reference = _reference_state(guild, field, raw_value)
    definition: dict[str, Any] = {
        "key": f"{category_key}.{field.attr}",
        "attr": field.attr,
        "label": _clean_label(field.label),
        "description": _FIELD_DESCRIPTIONS.get(field.attr, ""),
        "type": _field_type(field),
        "section": category_key,
        "section_title": category_title,
        "source_model": _model_name(field),
        "options": [
            {"value": str(value), "label": _clean_label(label)}
            for value, label in (field.choices or [])
        ],
        "required": field.kind == FieldKind.NUMBER and not field.allow_clear,
        "allow_clear": field.allow_clear,
        "status": reference["status"],
        "status_message": reference["message"],
        "missing_reference": reference.get("missing_reference", False),
    }
    if unit is not None:
        definition["unit"] = unit
        definition["unit_label"] = _DURATION_LABELS[unit]
        definition["display_units"] = [
            {"value": key, "label": label} for key, label in _DURATION_LABELS.items()
        ]
    return definition


def _serialize_value(raw: Any) -> Any:
    # bool precisa vir antes de int: em Python, bool herda de int.
    # Sem isso False virava "False" (string), e o toggle do frontend
    # continuava aparecendo como ativo porque string nao vazia e truthy.
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, uuid.UUID):
        return str(raw)
    if isinstance(raw, datetime):
        return raw.astimezone(UTC).isoformat()
    if isinstance(raw, list):
        return [
            str(item) if isinstance(item, int) and not isinstance(item, bool) else item
            for item in raw
        ]
    if isinstance(raw, int):
        return str(raw)
    return raw


def _coerce_number(field: SettingsField, value: Any) -> int | None:
    if value in ("", None):
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


def _coerce_duration_payload(field: SettingsField, value: Any) -> int | None:
    if not isinstance(value, dict):
        return _coerce_number(field, value)
    raw_amount = value.get("value")
    raw_unit = str(value.get("unit") or "")
    storage_unit = _unit_for(field)
    if storage_unit is None:
        return _coerce_number(field, raw_amount)
    if raw_amount in ("", None):
        if not field.allow_clear:
            raise ValueError("Campo obrigatorio.")
        return None
    if raw_unit not in _DURATION_UNITS[storage_unit]:
        raise ValueError("Unidade de tempo invalida.")
    try:
        amount = float(raw_amount)
    except (TypeError, ValueError) as exc:
        raise ValueError("Use um numero valido para o tempo.") from exc
    if amount < 0:
        raise ValueError("Use zero ou numero positivo.")
    return int(round(amount * _DURATION_UNITS[storage_unit][raw_unit]))


def _coerce_value(field: SettingsField, value: Any, guild: discord.Guild) -> Any:
    if value == "":
        value = None
    if field.kind in {FieldKind.CHANNEL, FieldKind.ROLE}:
        if value is None:
            return None
        try:
            coerced = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("ID invalido.") from exc
        _validate_reference(guild, field, coerced)
        return coerced
    if field.kind == FieldKind.ROLE_MULTI:
        if not isinstance(value, list):
            raise ValueError("Lista de cargos invalida.")
        try:
            coerced = [int(item) for item in value]
        except (TypeError, ValueError) as exc:
            raise ValueError("Lista de cargos contem ID invalido.") from exc
        _validate_reference(guild, field, coerced)
        return coerced
    if field.kind == FieldKind.NUMBER:
        return _coerce_duration_payload(field, value)
    if field.kind == FieldKind.BOOL:
        if not isinstance(value, bool):
            raise ValueError("Use verdadeiro ou falso.")
        return value
    if field.kind == FieldKind.CHOICE:
        if not field.choices:
            return str(value or "").strip() or None
        raw = str(value)
        allowed = {str(option) for option, _ in field.choices}
        if raw not in allowed:
            raise ValueError("Opcao invalida.")
        return raw
    if field.kind == FieldKind.TEXT:
        return str(value).strip() or None
    return value


def _resolve_legacy_key(raw_key: str, updaters: dict[str, _UpdaterEntry]) -> str | None:
    if raw_key in updaters:
        return raw_key
    matches = [key for key, entry in updaters.items() if entry.field.attr == raw_key]
    if len(matches) == 1:
        return matches[0]
    return None


async def _settings_bundle(bot: Any, guild_id: int, guild: discord.Guild) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, _UpdaterEntry]]:
    sections: list[dict[str, Any]] = []
    values: dict[str, Any] = {}
    updaters: dict[str, _UpdaterEntry] = {}
    seen: set[str] = set()

    for category_key, title, fields, get_settings, update_settings in iter_categories(bot):
        section_title = _clean_label(title)
        definitions: list[dict[str, Any]] = []
        settings = await get_settings(guild_id)
        for field in fields:
            namespaced_key = f"{category_key}.{field.attr}"
            if namespaced_key in seen:
                raise RuntimeError(f"Configuracao duplicada no dashboard: {namespaced_key}")
            seen.add(namespaced_key)
            raw_value = getattr(settings, field.attr)
            definitions.append(_setting_definition(category_key, section_title, field, raw_value, guild))
            values[namespaced_key] = _serialize_value(raw_value)
            updaters[namespaced_key] = _UpdaterEntry(category_key, section_title, field, update_settings)
        sections.append(
            {
                "key": category_key,
                "title": section_title,
                "description": _CATEGORY_DESCRIPTIONS.get(category_key, "Configuracoes deste modulo."),
                "fields": definitions,
            }
        )
    return sections, values, updaters


def _guild(bot: Any, guild_id: int | None = None):
    if guild_id is not None:
        return bot.get_guild(guild_id)
    if bot.settings.test_guild_id is not None:
        guild = bot.get_guild(bot.settings.test_guild_id)
        if guild is not None:
            return guild
    return bot.guilds[0] if bot.guilds else None


@router.get("/guild/{guild_id}/settings")
async def get_settings(request: Request, guild_id: int) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    if guild is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "GUILD_NOT_FOUND", "message": "Servidor nao encontrado."}})
    sections, values, _ = await _settings_bundle(bot, guild_id, guild)
    return {"guild_id": str(guild_id), "sections": sections, "values": values}


@router.patch("/guild/{guild_id}/settings")
async def update_settings(request: Request, guild_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    if guild is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "GUILD_NOT_FOUND", "message": "Servidor nao encontrado."}})
    raw_values = payload.get("values")
    if not isinstance(raw_values, dict):
        raise HTTPException(status_code=422, detail={"error": {"code": "INVALID_PAYLOAD", "message": "Envie um objeto values."}})

    _, before, updaters = await _settings_bundle(bot, guild_id, guild)
    grouped: dict[Any, dict[str, Any]] = {}
    changes: list[tuple[str, str, Any, Any]] = []

    for raw_key, raw_value in raw_values.items():
        key = _resolve_legacy_key(str(raw_key), updaters)
        if key is None:
            raise HTTPException(
                status_code=400,
                detail={"error": {"code": "INVALID_SETTING", "message": "Configuracao desconhecida ou ambigua.", "field": str(raw_key)}},
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
        if before.get(key) != _serialize_value(value):
            changes.append((entry.category_title, entry.field.label, before.get(key), _serialize_value(value)))

    for updater, values in grouped.items():
        await updater(guild_id, **values)

    for section, label, old, new in changes:
        await bot.audit_log_service.record_config_change(
            guild_id=guild_id,
            actor_id=0,
            actor_name="Painel web",
            config_category=section,
            config_name=_clean_label(label),
            old_value=str(old),
            new_value=str(new),
        )

    sections, values, _ = await _settings_bundle(bot, guild_id, guild)
    return {"guild_id": str(guild_id), "sections": sections, "values": values}
