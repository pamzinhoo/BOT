from __future__ import annotations

import enum
import hashlib
import json
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import discord

from database.models.audit_log import AuditLogCategory
from database.models.permission_settings import PERMISSION_ACTIONS

if TYPE_CHECKING:
    from core.bot import LimerenceBot

CONFIG_EXPORT_VERSION = 1
_PYPROJECT_PATH = Path(__file__).resolve().parent.parent / "pyproject.toml"

# migracoes de config_version antigo -> atual. Vazio hoje (so existe v1);
# fica pronto pra quando surgir v2 (cada entrada recebe o dict cru e devolve
# o dict no formato da versao seguinte).
_MIGRATIONS: dict[int, Callable[[dict], dict]] = {}


def _get_bot_version() -> str:
    try:
        with open(_PYPROJECT_PATH, "rb") as f:
            return tomllib.load(f)["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "unknown"


class ConfigImportError(ValueError):
    """Arquivo de importacao invalido (versao, estrutura, checksum ou JSON malformado)."""


class RefKind(enum.Enum):
    CHANNEL = "channel"
    ROLE = "role"
    ROLE_LIST = "role_list"
    PLAIN = "plain"


TABLE_SCHEMAS: dict[str, list[tuple[str, RefKind]]] = {
    "guild_settings": [
        ("log_channel_id", RefKind.CHANNEL),
        ("reports_channel_id", RefKind.CHANNEL),
        ("evaluations_channel_id", RefKind.CHANNEL),
        ("moderator_role_id", RefKind.ROLE),
        ("dev_role_id", RefKind.ROLE),
        ("ceo_role_id", RefKind.ROLE),
        ("owner_role_id", RefKind.ROLE),
        ("support_role_id", RefKind.ROLE),
        ("partner_role_id", RefKind.ROLE),
        ("streamer_role_id", RefKind.ROLE),
        ("inactive_after_minutes", RefKind.PLAIN),
        ("ticket_category_id", RefKind.CHANNEL),
        ("ticket_alert_channel_id", RefKind.CHANNEL),
        ("transcript_channel_id", RefKind.CHANNEL),
        ("blacklist_channel_id", RefKind.CHANNEL),
        ("backup_channel_id", RefKind.CHANNEL),
        ("dashboard_channel_id", RefKind.CHANNEL),
        ("ranking_channel_id", RefKind.CHANNEL),
    ],
    "ticket_settings": [
        ("enabled", RefKind.PLAIN),
        ("max_tickets_per_user", RefKind.PLAIN),
        ("allow_multiple_tickets", RefKind.PLAIN),
        ("auto_close_enabled", RefKind.PLAIN),
        ("delete_delay_seconds", RefKind.PLAIN),
        ("category_selection_mode", RefKind.PLAIN),
    ],
    "evaluation_settings": [
        ("enabled", RefKind.PLAIN),
        ("min_comment_rating", RefKind.PLAIN),
        ("star_emoji", RefKind.PLAIN),
        ("evaluation_method", RefKind.PLAIN),
        ("dm_embed_title", RefKind.PLAIN),
        ("dm_embed_description", RefKind.PLAIN),
        ("dm_prompt_text", RefKind.PLAIN),
        ("dm_button_label", RefKind.PLAIN),
        ("dm_thanks_message", RefKind.PLAIN),
    ],
    "dashboard_settings": [
        ("auto_update_enabled", RefKind.PLAIN),
        ("update_interval_minutes", RefKind.PLAIN),
        ("top_count", RefKind.PLAIN),
        ("show_chart", RefKind.PLAIN),
    ],
    "ranking_settings": [
        ("criteria", RefKind.PLAIN),
        ("default_period", RefKind.PLAIN),
    ],
    "anti_spam_settings": [
        ("window_seconds", RefKind.PLAIN),
        ("cross_channel_threshold", RefKind.PLAIN),
        ("flood_window_seconds", RefKind.PLAIN),
        ("flood_threshold", RefKind.PLAIN),
        ("repeat_threshold", RefKind.PLAIN),
        ("ignore_staff", RefKind.PLAIN),
        ("default_action", RefKind.PLAIN),
    ],
    "permission_settings": [(action, RefKind.ROLE_LIST) for action in PERMISSION_ACTIONS],
    "audit_log_settings": [
        ("channel_id", RefKind.CHANNEL),
        *[(category.value, RefKind.PLAIN) for category in AuditLogCategory],
    ],
}

# categoria (mesmas usadas no /config painel) -> tabela inteira que pertence so a ela
_TABLE_CATEGORY: dict[str, str] = {
    "ticket_settings": "tickets",
    "permission_settings": "permissoes",
    "dashboard_settings": "dashboard",
    "ranking_settings": "ranking",
    "audit_log_settings": "auditoria",
    "anti_spam_settings": "antispam",
    "evaluation_settings": "avaliacoes",
}

# guild_settings mistura campos de varias categorias — mapeia atributo -> categoria
_GUILD_SETTINGS_CATEGORY: dict[str, str] = {
    "ticket_category_id": "tickets",
    "log_channel_id": "tickets",
    "transcript_channel_id": "tickets",
    "blacklist_channel_id": "antispam",
    "inactive_after_minutes": "tickets",
    "owner_role_id": "cargos",
    "ceo_role_id": "cargos",
    "dev_role_id": "cargos",
    "moderator_role_id": "cargos",
    "support_role_id": "cargos",
    "partner_role_id": "cargos",
    "streamer_role_id": "cargos",
    "dashboard_channel_id": "dashboard",
    "ranking_channel_id": "ranking",
    "evaluations_channel_id": "avaliacoes",
    "ticket_alert_channel_id": "alertas",
}

IMPORT_SECTIONS: list[tuple[str, str]] = [
    ("tickets", "🎫 Tickets"),
    ("cargos", "👮 Cargos"),
    ("permissoes", "🔐 Permissões"),
    ("dashboard", "📊 Dashboard"),
    ("ranking", "📈 Ranking"),
    ("avaliacoes", "⭐ Avaliações"),
    ("antispam", "🚫 Anti-Spam"),
    ("auditoria", "📋 Auditoria"),
    ("alertas", "🔔 Alertas"),
]


def _field_category(table: str, attr: str) -> str | None:
    if table == "guild_settings":
        return _GUILD_SETTINGS_CATEGORY.get(attr)
    return _TABLE_CATEGORY.get(table)

# tabela -> nome do metodo get_*/update_* em bot.config_service (ou "audit" pra bot.audit_log_service)
_SERVICE_METHODS: dict[str, str] = {
    "guild_settings": "settings",
    "ticket_settings": "ticket_settings",
    "evaluation_settings": "evaluation_settings",
    "dashboard_settings": "dashboard_settings",
    "ranking_settings": "ranking_settings",
    "anti_spam_settings": "anti_spam_settings",
    "permission_settings": "permission_settings",
    "audit_log_settings": "audit",
}


async def _get_table_settings(bot: LimerenceBot, table: str, guild_id: int) -> object:
    suffix = _SERVICE_METHODS[table]
    if suffix == "audit":
        return await bot.audit_log_service.get_settings(guild_id)
    return await getattr(bot.config_service, f"get_{suffix}")(guild_id)


async def _update_table_settings(bot: LimerenceBot, table: str, guild_id: int, **fields: object) -> None:
    suffix = _SERVICE_METHODS[table]
    if suffix == "audit":
        await bot.audit_log_service.update_settings(guild_id, **fields)
        return
    await getattr(bot.config_service, f"update_{suffix}")(guild_id, **fields)


def _label(attr: str) -> str:
    return attr.removesuffix("_id").replace("_", " ").strip().title()


def _export_channel(guild: discord.Guild, channel_id: int | None) -> dict | None:
    if channel_id is None:
        return None
    channel = guild.get_channel(channel_id)
    return {"id": channel_id, "name": channel.name if channel else None}


def _export_role(guild: discord.Guild, role_id: int | None) -> dict | None:
    if role_id is None:
        return None
    role = guild.get_role(role_id)
    return {"id": role_id, "name": role.name if role else None}


def _checksum(data: dict) -> str:
    """SHA-256 do JSON canonico (chaves ordenadas), sem o campo 'checksum'."""
    payload = {k: v for k, v in data.items() if k != "checksum"}
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


async def export_guild_config(bot: LimerenceBot, guild: discord.Guild) -> dict:
    data: dict = {
        "config_version": CONFIG_EXPORT_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "bot_version": _get_bot_version(),
        "guild_id": guild.id,
        "guild_name": guild.name,
        "generated_by": "BOT LIMERENCE",
    }
    for table, schema in TABLE_SCHEMAS.items():
        settings = await _get_table_settings(bot, table, guild.id)
        table_data: dict = {}
        for attr, kind in schema:
            raw = getattr(settings, attr)
            if kind == RefKind.CHANNEL:
                table_data[attr] = _export_channel(guild, raw)
            elif kind == RefKind.ROLE:
                table_data[attr] = _export_role(guild, raw)
            elif kind == RefKind.ROLE_LIST:
                table_data[attr] = [r for r in (_export_role(guild, rid) for rid in (raw or [])) if r]
            else:
                table_data[attr] = raw
        data[table] = table_data

    data["checksum"] = _checksum(data)
    return data


@dataclass
class ImportFieldChange:
    table: str
    attr: str
    label: str
    kind: RefKind
    status: str  # "matched_id" | "matched_name" | "unresolved" | "value"
    old_value: object
    new_value: object
    ref_name: str | None = None  # nome do canal/cargo referenciado, pra mensagem de erro
    included: bool = True  # False = fora da selecao de secoes do import parcial, nao sera aplicado

    @property
    def changed(self) -> bool:
        return self.included and self.old_value != self.new_value


def _resolve_channel_import(guild: discord.Guild, entry: dict | None) -> tuple[int | None, str, str | None]:
    if not entry:
        return None, "value", None
    channel = guild.get_channel(entry.get("id")) if entry.get("id") else None
    if channel is not None:
        return channel.id, "matched_id", channel.name
    name = entry.get("name")
    if name:
        match = discord.utils.get(guild.channels, name=name)
        if match is not None:
            return match.id, "matched_name", match.name
    return None, "unresolved", name


def _resolve_role_import(guild: discord.Guild, entry: dict | None) -> tuple[int | None, str, str | None]:
    if not entry:
        return None, "value", None
    role = guild.get_role(entry.get("id")) if entry.get("id") else None
    if role is not None:
        return role.id, "matched_id", role.name
    name = entry.get("name")
    if name:
        match = discord.utils.get(guild.roles, name=name)
        if match is not None:
            return match.id, "matched_name", match.name
    return None, "unresolved", name


def _check_integrity(data: dict) -> str:
    """Retorna 'ok' | 'missing' | 'mismatch'. Nao bloqueia sozinha — quem chama decide."""
    provided = data.get("checksum")
    if provided is None:
        return "missing"
    recomputed = _checksum(data)
    return "ok" if provided == recomputed else "mismatch"


def _migrate_to_current(data: dict) -> dict:
    version = data.get("config_version")
    if not isinstance(version, int):
        raise ConfigImportError("Campo 'config_version' ausente ou inválido.")
    if version > CONFIG_EXPORT_VERSION:
        raise ConfigImportError(
            f"Arquivo de uma versão mais nova ({version}) do que este bot suporta "
            f"({CONFIG_EXPORT_VERSION}). Atualize o bot antes de importar."
        )
    while version < CONFIG_EXPORT_VERSION:
        migrate = _MIGRATIONS.get(version)
        if migrate is None:
            raise ConfigImportError(
                f"Não existe caminho de migração da versão {version} pra {CONFIG_EXPORT_VERSION}."
            )
        data = migrate(data)
        version = data.get("config_version", version + 1)
    return data


def _validate_structure(data: dict) -> None:
    if not isinstance(data, dict):
        raise ConfigImportError("Arquivo inválido — esperado um objeto JSON.")
    for table in TABLE_SCHEMAS:
        if table not in data or not isinstance(data[table], dict):
            raise ConfigImportError(f"Arquivo incompleto ou corrompido — falta a seção '{table}'.")


async def build_import_plan(
    bot: LimerenceBot,
    guild: discord.Guild,
    data: dict,
    *,
    sections: set[str] | None = None,
) -> tuple[dict[str, dict[str, object]], list[ImportFieldChange], str]:
    """`sections=None` importa tudo. Retorna (plan, changes, integrity) onde
    integrity e 'ok'/'missing'/'mismatch' do checksum do arquivo."""
    integrity = _check_integrity(data)
    if integrity == "mismatch":
        raise ConfigImportError(
            "Checksum não confere — o arquivo parece ter sido alterado ou corrompido."
        )

    data = _migrate_to_current(data)
    _validate_structure(data)

    plan: dict[str, dict[str, object]] = {}
    changes: list[ImportFieldChange] = []

    for table, schema in TABLE_SCHEMAS.items():
        current = await _get_table_settings(bot, table, guild.id)
        table_input = data[table]
        table_plan: dict[str, object] = {}

        for attr, kind in schema:
            old_value = getattr(current, attr)
            category = _field_category(table, attr)
            included = sections is None or category is None or category in sections

            if not included:
                table_plan[attr] = old_value
                changes.append(
                    ImportFieldChange(
                        table=table,
                        attr=attr,
                        label=_label(attr),
                        kind=kind,
                        status="value",
                        old_value=old_value,
                        new_value=old_value,
                        included=False,
                    )
                )
                continue

            if attr not in table_input:
                # campo novo, ausente num arquivo exportado por uma versao
                # anterior do bot — mantem o valor atual em vez de zerar pra
                # None (que quebraria coluna NOT NULL tipo category_selection_mode).
                table_plan[attr] = old_value
                changes.append(
                    ImportFieldChange(
                        table=table,
                        attr=attr,
                        label=_label(attr),
                        kind=kind,
                        status="value",
                        old_value=old_value,
                        new_value=old_value,
                    )
                )
                continue

            entry = table_input.get(attr)

            if kind == RefKind.CHANNEL:
                new_value, status, ref_name = _resolve_channel_import(guild, entry)
            elif kind == RefKind.ROLE:
                new_value, status, ref_name = _resolve_role_import(guild, entry)
            elif kind == RefKind.ROLE_LIST:
                resolved = [_resolve_role_import(guild, e) for e in (entry or [])]
                new_value = [rid for rid, status, _ in resolved if rid is not None]
                unresolved_names = [name for rid, status, name in resolved if rid is None and name]
                status = "unresolved" if unresolved_names else "value"
                ref_name = ", ".join(unresolved_names) if unresolved_names else None
            else:
                new_value, status, ref_name = entry, "value", None

            table_plan[attr] = new_value
            changes.append(
                ImportFieldChange(
                    table=table,
                    attr=attr,
                    label=_label(attr),
                    kind=kind,
                    status=status,
                    old_value=old_value,
                    new_value=new_value,
                    ref_name=ref_name,
                )
            )

        plan[table] = table_plan

    return plan, changes, integrity


async def apply_import_plan(bot: LimerenceBot, guild_id: int, plan: dict[str, dict[str, object]]) -> None:
    for table, fields in plan.items():
        await _update_table_settings(bot, table, guild_id, **fields)


def _conflict_summary(changes: list[ImportFieldChange]) -> str:
    channel_found = channel_missing = role_found = role_missing = 0
    for c in changes:
        if c.kind == RefKind.CHANNEL:
            if c.status == "unresolved":
                channel_missing += 1
            elif c.status in ("matched_id", "matched_name"):
                channel_found += 1
        elif c.kind == RefKind.ROLE:
            if c.status == "unresolved":
                role_missing += 1
            elif c.status in ("matched_id", "matched_name"):
                role_found += 1
        elif c.kind == RefKind.ROLE_LIST:
            role_found += len(c.new_value or [])
            role_missing += len(c.ref_name.split(", ")) if c.ref_name else 0

    lines = [
        f"Canais\n✅ {channel_found} encontrado(s)"
        + (f"\n⚠️ {channel_missing} não encontrado(s)" if channel_missing else ""),
        f"Cargos\n✅ {role_found} encontrado(s)"
        + (f"\n⚠️ {role_missing} não encontrado(s)" if role_missing else ""),
    ]
    return "\n\n".join(lines)


def build_preview_embed(
    changes: list[ImportFieldChange], integrity: str = "ok", *, dry_run: bool = False
) -> discord.Embed:
    embed = discord.Embed(title="🧪 Simulação de importação" if dry_run else "📋 Prévia da importação")
    if dry_run:
        embed.description = "Modo simulação — nenhuma alteração será salva."
    if integrity == "missing":
        embed.add_field(
            name="ℹ️ Integridade",
            value="Arquivo sem checksum (gerado antes desse recurso) — sem verificação de integridade.",
            inline=False,
        )

    embed.add_field(name="Resumo de canais/cargos", value=_conflict_summary(changes), inline=False)

    excluded_count = sum(1 for c in changes if not c.included)
    if excluded_count:
        embed.add_field(
            name="Fora da seleção",
            value=f"{excluded_count} campo(s) não fazem parte das seções escolhidas e não serão alterados.",
            inline=False,
        )

    changed = [c for c in changes if c.changed and c.status != "unresolved"]
    unresolved = [c for c in changes if c.included and c.status == "unresolved"]

    if changed:
        by_table: dict[str, list[ImportFieldChange]] = {}
        for c in changed:
            by_table.setdefault(c.table, []).append(c)
        for table, table_changes in by_table.items():
            if len(table_changes) <= 6:
                lines = [f"**{c.label}**: {c.old_value} → {c.new_value}" for c in table_changes]
            else:
                lines = [f"{len(table_changes)} campos serão alterados."]
            embed.add_field(name=table, value="\n".join(lines)[:1024], inline=False)
    else:
        embed.description = "Nenhuma mudança detectada em relação à configuração atual."

    if unresolved:
        lines = [f"`{c.table}.{c.attr}`: **{c.ref_name or '?'}** não encontrado neste servidor" for c in unresolved]
        embed.add_field(name="⚠️ Não resolvidos (ficarão vazios)", value="\n".join(lines)[:1024], inline=False)

    return embed
