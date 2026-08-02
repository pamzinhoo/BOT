from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord
from views.base_view import SafeView

from database.models.audit_log import AuditLogCategory
from database.models.audit_log_settings import AuditLogSettings
from utils.constants import AUDIT_CATEGORY_LABELS
from utils.model_defaults import diff_defaults

if TYPE_CHECKING:
    from core.bot import LimerenceBot

# (atributo em AuditLogSettings, rotulo)
_CATEGORIES: list[tuple[str, str]] = [
    (category.value, label) for category, label in AUDIT_CATEGORY_LABELS.items()
]
_LABEL_BY_ATTR: dict[str, str] = dict(_CATEGORIES) | {"channel_id": "Canal de Auditoria"}


def audit_log_summary_embed(settings: AuditLogSettings) -> discord.Embed:
    active = sum(1 for attr, _ in _CATEGORIES if getattr(settings, attr))
    embed = discord.Embed(title="🕵️ Auditoria do servidor")
    embed.add_field(
        name="Canal de auditoria",
        value=f"<#{settings.channel_id}>" if settings.channel_id else "— (só grava no banco)",
        inline=False,
    )
    embed.add_field(name="Categorias ativas", value=f"{active}/{len(_CATEGORIES)}", inline=False)
    embed.set_footer(text="Use o menu abaixo para ativar/desativar categorias.")
    return embed


_MAX_SELECT_OPTIONS = 25  # limite do Discord — _CATEGORIES pode passar disso, entao divide em paginas
_CATEGORY_PAGES: list[list[tuple[str, str]]] = [
    _CATEGORIES[i : i + _MAX_SELECT_OPTIONS] for i in range(0, len(_CATEGORIES), _MAX_SELECT_OPTIONS)
]


class _CategoryToggleSelect(discord.ui.Select["AuditLogPanelView"]):
    """Um select por pagina de ate 25 categorias (limite do Discord). O
    callback so mexe nos attrs da SUA pagina — nunca reseta as outras."""

    def __init__(self, settings: AuditLogSettings, page: list[tuple[str, str]], *, row: int) -> None:
        options = [
            discord.SelectOption(label=label, value=attr, default=getattr(settings, attr))
            for attr, label in page
        ]
        super().__init__(
            placeholder="Selecione as categorias que devem ser auditadas...",
            options=options,
            min_values=0,
            max_values=len(options),
            row=row,
        )
        self.page = page

    async def callback(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        selected = set(self.values)
        fields = {attr: attr in selected for attr, _ in self.page}
        await bot.audit_log_service.update_settings(interaction.guild_id, **fields)
        settings = await bot.audit_log_service.get_settings(interaction.guild_id)
        await interaction.response.edit_message(
            embed=audit_log_summary_embed(settings), view=AuditLogPanelView(settings)
        )


class AuditLogPanelView(SafeView):
    """Painel de toggle das categorias de auditoria. Nao-persistente (timeout=300) —
    utilitario de admin aberto sob demanda, igual as demais views do /config."""

    def __init__(self, settings: AuditLogSettings) -> None:
        super().__init__(timeout=300)
        for row, page in enumerate(_CATEGORY_PAGES):
            self.add_item(_CategoryToggleSelect(settings, page, row=row))
        self.add_item(_ResetAuditButton(row=len(_CATEGORY_PAGES)))
        self.add_item(_BackToMainMenuButton())


class _BackToMainMenuButton(discord.ui.Button[Any]):
    def __init__(self) -> None:
        super().__init__(label="◀ Menu principal", style=discord.ButtonStyle.secondary, row=4)

    async def callback(self, interaction: discord.Interaction) -> None:
        from views.master_config_view import main_menu_embed, MainConfigMenuView

        await interaction.response.edit_message(
            content=None, embed=main_menu_embed(), view=MainConfigMenuView()
        )


def _format_audit_value(attr: str, value: object) -> str:
    if attr == "channel_id":
        return f"<#{value}>" if value else "—"
    return "✅ Ativado" if value else "❌ Desativado"


class _ResetAuditButton(discord.ui.Button[Any]):
    def __init__(self, *, row: int = 1) -> None:
        super().__init__(label="🔄 Restaurar padrão", style=discord.ButtonStyle.danger, row=row)

    async def callback(self, interaction: discord.Interaction) -> None:
        from core.bot import LimerenceBot  # import tardio evita ciclo

        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        settings = await bot.audit_log_service.get_settings(interaction.guild_id)
        diffs = diff_defaults(settings)

        embed = discord.Embed(title="🔄 Restaurar padrão — 📋 Auditoria")
        if diffs:
            embed.description = (
                "Isso vai restaurar **apenas a categoria Auditoria** para os valores padrão "
                "(canal e categorias monitoradas). O histórico de auditoria não é apagado."
            )
            for attr, (before, after) in diffs.items():
                embed.add_field(
                    name=_LABEL_BY_ATTR.get(attr, attr),
                    value=f"{_format_audit_value(attr, before)} → {_format_audit_value(attr, after)}",
                    inline=False,
                )
        else:
            embed.description = "A categoria Auditoria já está nos valores padrão — nada para restaurar."

        await interaction.response.edit_message(
            content=None, embed=embed, view=_AuditResetConfirmView(settings, enabled=bool(diffs))
        )


class _AuditResetConfirmView(SafeView):
    def __init__(self, settings: AuditLogSettings, *, enabled: bool) -> None:
        super().__init__(timeout=120)
        confirm = _ConfirmAuditResetButton()
        confirm.disabled = not enabled
        self.add_item(confirm)
        self.add_item(_CancelAuditResetButton())


class _ConfirmAuditResetButton(discord.ui.Button[Any]):
    def __init__(self) -> None:
        super().__init__(label="Confirmar restauração", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction) -> None:
        from core.bot import LimerenceBot  # import tardio evita ciclo

        assert interaction.guild_id is not None
        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        diffs = await bot.audit_log_service.reset_settings(interaction.guild_id)
        await bot.audit_log_service.record(
            guild_id=interaction.guild_id,
            category=AuditLogCategory.SERVER_CONFIG,
            action="Categoria restaurada para padrão",
            executor_id=interaction.user.id,
            executor_name=str(interaction.user),
            config_category="Auditoria",
            config_name="Reset de Categoria",
            old_value=f"{len(diffs)} configuração(ões) personalizada(s)",
            new_value="Restaurado para o padrão",
        )
        settings = await bot.audit_log_service.get_settings(interaction.guild_id)
        await interaction.response.edit_message(
            content=None, embed=audit_log_summary_embed(settings), view=AuditLogPanelView(settings)
        )


class _CancelAuditResetButton(discord.ui.Button[Any]):
    def __init__(self) -> None:
        super().__init__(label="Cancelar", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        from core.bot import LimerenceBot  # import tardio evita ciclo

        bot: LimerenceBot = interaction.client  # type: ignore[assignment]
        settings = await bot.audit_log_service.get_settings(interaction.guild_id)
        await interaction.response.edit_message(
            content=None, embed=audit_log_summary_embed(settings), view=AuditLogPanelView(settings)
        )
