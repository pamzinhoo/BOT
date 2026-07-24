from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import discord

from database.models.anti_spam_settings import AntiSpamSettings
from database.models.bot_status_settings import BotStatusSettings
from database.models.dashboard_settings import DashboardSettings
from database.models.evaluation_settings import EvaluationSettings
from database.models.guild_settings import GuildSettings
from database.models.permission_settings import PermissionSettings
from database.models.ranking_settings import RankingSettings
from database.models.ticket_settings import TicketSettings
from services.ranking_service import RankingPeriod
from views.audit_log_panel_view import AuditLogPanelView, audit_log_summary_embed
from views.settings_panel import DomainSettingsView, FieldKind, GetSettings, SettingsField, UpdateSettings

if TYPE_CHECKING:
    from core.bot import LimerenceBot

_TEXT = [discord.ChannelType.text, discord.ChannelType.news]
_CATEGORY_CHANNEL = [discord.ChannelType.category]

_PERIOD_CHOICES = [(p.value, label) for p, label in [
    (RankingPeriod.DAILY, "Hoje"),
    (RankingPeriod.WEEKLY, "Semana"),
    (RankingPeriod.MONTHLY, "Mês"),
    (RankingPeriod.ALLTIME, "Geral"),
]]

_PERMISSION_ACTIONS = ["claim", "unclaim", "fechar", "reabrir", "excluir", "auditoria", "ranking", "config"]
_PERMISSION_LABELS = {
    "claim": "Quem pode Assumir",
    "unclaim": "Quem pode Liberar",
    "fechar": "Quem pode Fechar",
    "reabrir": "Quem pode Reabrir",
    "excluir": "Quem pode Excluir",
    "auditoria": "Quem pode usar Auditoria",
    "ranking": "Quem pode usar Ranking",
    "config": "Quem pode usar Config",
}


class _Merged:
    """Combina 2+ objetos de settings pra leitura — getattr tenta cada fonte em ordem."""

    def __init__(self, *sources: object) -> None:
        self._sources = sources

    def __getattr__(self, name: str) -> Any:
        for source in self._sources:
            if hasattr(source, name):
                return getattr(source, name)
        raise AttributeError(name)


def _dispatch(bot: "LimerenceBot", routing: dict[str, str]) -> UpdateSettings:
    """Cria um update_settings(guild_id, **fields) que manda cada campo pro
    metodo certo do ConfigService/AuditLogService, conforme `routing`
    (attr -> nome do metodo update_* em bot.config_service ou "audit")."""

    async def _update(guild_id: int, **fields: object) -> None:
        for key, value in fields.items():
            method_name = routing[key]
            if method_name == "audit":
                await bot.audit_log_service.update_settings(guild_id, **{key: value})
            else:
                method = getattr(bot.config_service, method_name)
                await method(guild_id, **{key: value})

    return _update


def _tickets_category(bot: "LimerenceBot") -> tuple[list[SettingsField], GetSettings, UpdateSettings]:
    fields = [
        SettingsField("ticket_category_id", "Categoria de Tickets", FieldKind.CHANNEL, GuildSettings, channel_types=_CATEGORY_CHANNEL),
        SettingsField("log_channel_id", "Canal de Logs", FieldKind.CHANNEL, GuildSettings, channel_types=_TEXT),
        SettingsField("transcript_channel_id", "Canal de Transcrição", FieldKind.CHANNEL, GuildSettings, channel_types=_TEXT),
        SettingsField("evaluations_channel_id", "Canal de Avaliações", FieldKind.CHANNEL, GuildSettings, channel_types=_TEXT),
        SettingsField("ticket_alert_channel_id", "Canal de Alerta", FieldKind.CHANNEL, GuildSettings, channel_types=_TEXT),
        SettingsField("blacklist_channel_id", "Canal de Blacklist", FieldKind.CHANNEL, GuildSettings, channel_types=_TEXT),
        SettingsField("max_tickets_per_user", "Máximo de Tickets por Usuário", FieldKind.NUMBER, TicketSettings),
        SettingsField("allow_multiple_tickets", "Permitir Múltiplos Tickets", FieldKind.BOOL, TicketSettings),
        SettingsField("auto_close_enabled", "Auto-Close Ativado", FieldKind.BOOL, TicketSettings),
        SettingsField("inactive_after_minutes", "Tempo de Inatividade (min)", FieldKind.NUMBER, GuildSettings),
        SettingsField("delete_delay_seconds", "Delay de Exclusão (segundos)", FieldKind.NUMBER, TicketSettings, allow_clear=False),
    ]

    async def get_settings(guild_id: int) -> _Merged:
        g, t = await asyncio.gather(
            bot.config_service.get_settings(guild_id),
            bot.config_service.get_ticket_settings(guild_id),
        )
        return _Merged(t, g)

    routing = {
        "ticket_category_id": "update",
        "log_channel_id": "update",
        "transcript_channel_id": "update",
        "evaluations_channel_id": "update",
        "ticket_alert_channel_id": "update",
        "blacklist_channel_id": "update",
        "max_tickets_per_user": "update_ticket_settings",
        "allow_multiple_tickets": "update_ticket_settings",
        "auto_close_enabled": "update_ticket_settings",
        "inactive_after_minutes": "update",
        "delete_delay_seconds": "update_ticket_settings",
    }
    return fields, get_settings, _dispatch(bot, routing)


def _cargos_category(bot: "LimerenceBot") -> tuple[list[SettingsField], GetSettings, UpdateSettings]:
    fields = [
        SettingsField("owner_role_id", "Owner", FieldKind.ROLE, GuildSettings),
        SettingsField("ceo_role_id", "CEO", FieldKind.ROLE, GuildSettings),
        SettingsField("dev_role_id", "Desenvolvedor", FieldKind.ROLE, GuildSettings),
        SettingsField("moderator_role_id", "Moderador", FieldKind.ROLE, GuildSettings),
        SettingsField("support_role_id", "Suporte", FieldKind.ROLE, GuildSettings),
        SettingsField("partner_role_id", "Parceiro", FieldKind.ROLE, GuildSettings),
        SettingsField("streamer_role_id", "Streamer", FieldKind.ROLE, GuildSettings),
    ]

    async def get_settings(guild_id: int) -> Any:
        return await bot.config_service.get_settings(guild_id)

    return fields, get_settings, bot.config_service.update


def _permissoes_category(bot: "LimerenceBot") -> tuple[list[SettingsField], GetSettings, UpdateSettings]:
    fields = [
        SettingsField(action, _PERMISSION_LABELS[action], FieldKind.ROLE_MULTI, PermissionSettings)
        for action in _PERMISSION_ACTIONS
    ]

    async def get_settings(guild_id: int) -> Any:
        return await bot.config_service.get_permission_settings(guild_id)

    return fields, get_settings, bot.config_service.update_permission_settings


def _dashboard_category(bot: "LimerenceBot") -> tuple[list[SettingsField], GetSettings, UpdateSettings]:
    fields = [
        SettingsField("dashboard_channel_id", "Canal", FieldKind.CHANNEL, GuildSettings, channel_types=_TEXT),
        SettingsField("auto_update_enabled", "Atualização Automática", FieldKind.BOOL, DashboardSettings),
        SettingsField("update_interval_minutes", "Intervalo (min)", FieldKind.NUMBER, DashboardSettings, allow_clear=False),
        SettingsField(
            "top_count", "Quantidade no Top", FieldKind.CHOICE, DashboardSettings,
            choices=[("5", "Top 5"), ("10", "Top 10")],
        ),
        SettingsField("show_chart", "Mostrar Gráfico", FieldKind.BOOL, DashboardSettings),
    ]

    async def get_settings(guild_id: int) -> _Merged:
        g, d = await asyncio.gather(
            bot.config_service.get_settings(guild_id),
            bot.config_service.get_dashboard_settings(guild_id),
        )
        return _Merged(d, g)

    async def update_settings(guild_id: int, **updates: object) -> None:
        for key, value in updates.items():
            if key == "dashboard_channel_id":
                await bot.config_service.update(guild_id, dashboard_channel_id=value)
            elif key == "top_count":
                await bot.config_service.update_dashboard_settings(guild_id, top_count=int(value))
            else:
                await bot.config_service.update_dashboard_settings(guild_id, **{key: value})

    return fields, get_settings, update_settings


def _ranking_category(bot: "LimerenceBot") -> tuple[list[SettingsField], GetSettings, UpdateSettings]:
    fields = [
        SettingsField("ranking_channel_id", "Canal", FieldKind.CHANNEL, GuildSettings, channel_types=_TEXT),
        SettingsField(
            "criteria", "Critério", FieldKind.CHOICE, RankingSettings,
            choices=[("tickets", "Tickets fechados"), ("avaliacao", "Nota média")],
        ),
        SettingsField("default_period", "Período Padrão", FieldKind.CHOICE, RankingSettings, choices=_PERIOD_CHOICES),
    ]

    async def get_settings(guild_id: int) -> _Merged:
        g, r = await asyncio.gather(
            bot.config_service.get_settings(guild_id),
            bot.config_service.get_ranking_settings(guild_id),
        )
        return _Merged(r, g)

    async def update_settings(guild_id: int, **updates: object) -> None:
        for key, value in updates.items():
            if key == "ranking_channel_id":
                await bot.config_service.update(guild_id, ranking_channel_id=value, ranking_message_id=None)
                await bot.painel_service.refresh_dashboard(guild_id)
            else:
                await bot.config_service.update_ranking_settings(guild_id, **{key: value})

    return fields, get_settings, update_settings


def _avaliacoes_category(bot: "LimerenceBot") -> tuple[list[SettingsField], GetSettings, UpdateSettings]:
    fields = [
        SettingsField("evaluations_channel_id", "Canal", FieldKind.CHANNEL, GuildSettings, channel_types=_TEXT),
        SettingsField("enabled", "Avaliação Ativada", FieldKind.BOOL, EvaluationSettings),
        SettingsField("min_comment_rating", "Nota Mínima p/ Comentário Obrigatório", FieldKind.NUMBER, EvaluationSettings),
        SettingsField("star_emoji", "Emoji das Estrelas", FieldKind.CHOICE, EvaluationSettings, choices=[
            ("⭐", "⭐"), ("🌟", "🌟"), ("✨", "✨"), ("💫", "💫"),
        ]),
    ]

    async def get_settings(guild_id: int) -> _Merged:
        g, e = await asyncio.gather(
            bot.config_service.get_settings(guild_id),
            bot.config_service.get_evaluation_settings(guild_id),
        )
        return _Merged(e, g)

    async def update_settings(guild_id: int, **updates: object) -> None:
        for key, value in updates.items():
            if key == "evaluations_channel_id":
                await bot.config_service.update(guild_id, evaluations_channel_id=value)
            else:
                await bot.config_service.update_evaluation_settings(guild_id, **{key: value})

    return fields, get_settings, update_settings


def _antispam_category(bot: "LimerenceBot") -> tuple[list[SettingsField], GetSettings, UpdateSettings]:
    fields = [
        SettingsField("blacklist_channel_id", "Canal de Alerta", FieldKind.CHANNEL, GuildSettings, channel_types=_TEXT),
        SettingsField("window_seconds", "Janela de Tempo (s)", FieldKind.NUMBER, AntiSpamSettings, allow_clear=False),
        SettingsField("cross_channel_threshold", "Qtd. de Canais p/ Detectar", FieldKind.NUMBER, AntiSpamSettings, allow_clear=False),
        SettingsField("flood_threshold", "Qtd. de Mensagens p/ Detectar Flood", FieldKind.NUMBER, AntiSpamSettings, allow_clear=False),
        SettingsField("ignore_staff", "Ignorar Staff", FieldKind.BOOL, AntiSpamSettings),
        SettingsField("default_action", "Ação Padrão", FieldKind.CHOICE, AntiSpamSettings, choices=[
            ("alerta", "Somente alertar"), ("apagar_mensagem", "Apagar mensagem"),
        ]),
    ]

    async def get_settings(guild_id: int) -> _Merged:
        g, a = await asyncio.gather(
            bot.config_service.get_settings(guild_id),
            bot.config_service.get_anti_spam_settings(guild_id),
        )
        return _Merged(a, g)

    async def update_settings(guild_id: int, **updates: object) -> None:
        for key, value in updates.items():
            if key == "blacklist_channel_id":
                await bot.config_service.update(guild_id, blacklist_channel_id=value)
            else:
                await bot.config_service.update_anti_spam_settings(guild_id, **{key: value})

    return fields, get_settings, update_settings


def _status_category(bot: "LimerenceBot") -> tuple[list[SettingsField], GetSettings, UpdateSettings]:
    fields = [
        SettingsField("channel_id", "Canal", FieldKind.CHANNEL, BotStatusSettings, channel_types=_TEXT),
        SettingsField(
            "update_interval_minutes", "Intervalo de Atualização (min)", FieldKind.NUMBER,
            BotStatusSettings, allow_clear=False,
        ),
    ]

    async def get_settings(guild_id: int) -> Any:
        return await bot.config_service.get_bot_status_settings(guild_id)

    async def update_settings(guild_id: int, **updates: object) -> None:
        for key, value in updates.items():
            if key == "channel_id":
                await bot.config_service.update_bot_status_settings(
                    guild_id, channel_id=value, message_id=None
                )
                await bot.bot_status_service.refresh(guild_id)
            else:
                await bot.config_service.update_bot_status_settings(guild_id, **{key: value})

    return fields, get_settings, update_settings


def _alertas_category(bot: "LimerenceBot") -> tuple[list[SettingsField], GetSettings, UpdateSettings]:
    fields = [
        SettingsField("ticket_alert_channel_id", "Canal de Alerta de Tickets", FieldKind.CHANNEL, GuildSettings, channel_types=_TEXT),
    ]

    async def get_settings(guild_id: int) -> Any:
        return await bot.config_service.get_settings(guild_id)

    return fields, get_settings, bot.config_service.update


_CATEGORY_BUILDERS: dict[str, tuple[str, Any]] = {
    "tickets": ("🎫 Tickets", _tickets_category),
    "cargos": ("👮 Cargos", _cargos_category),
    "permissoes": ("🔐 Permissões", _permissoes_category),
    "dashboard": ("📊 Dashboard", _dashboard_category),
    "ranking": ("📈 Ranking", _ranking_category),
    "avaliacoes": ("⭐ Avaliações", _avaliacoes_category),
    "antispam": ("🚫 Anti-Spam", _antispam_category),
    "alertas": ("🔔 Alertas", _alertas_category),
}


def iter_categories(
    bot: "LimerenceBot",
) -> list[tuple[str, str, list[SettingsField], GetSettings, UpdateSettings]]:
    """Todas as categorias resetáveis do painel: (chave, título, fields, get_settings,
    update_settings). Usado pelo reset geral (/config reset-all) pra reaproveitar
    exatamente os mesmos campos e defaults do painel — sem duplicar a lista em outro lugar."""
    return [
        (key, title, *builder(bot)) for key, (title, builder) in _CATEGORY_BUILDERS.items()
    ]


async def _open_category(interaction: discord.Interaction, category: str) -> None:
    assert interaction.guild_id is not None
    bot: LimerenceBot = interaction.client  # type: ignore[assignment]

    if category == "auditoria":
        settings = await bot.audit_log_service.get_settings(interaction.guild_id)
        await interaction.response.edit_message(
            content=None, embed=audit_log_summary_embed(settings), view=AuditLogPanelView(settings)
        )
        return

    if category == "geral":
        settings = await bot.config_service.get_settings(interaction.guild_id)
        embed = discord.Embed(title="⚙️ Geral — visão completa")
        embed.add_field(name="Canal de Dashboard", value=f"<#{settings.dashboard_channel_id}>" if settings.dashboard_channel_id else "—")
        embed.add_field(name="Canal de Backup", value=f"<#{settings.backup_channel_id}>" if settings.backup_channel_id else "—")
        embed.add_field(name="Categoria de Tickets", value=f"<#{settings.ticket_category_id}>" if settings.ticket_category_id else "—")
        embed.set_footer(text="Configurações específicas: use as outras categorias no menu.")
        view = discord.ui.View(timeout=300)
        view.add_item(_BackToMainMenuButton())
        await interaction.response.edit_message(content=None, embed=embed, view=view)
        return

    title, builder = _CATEGORY_BUILDERS[category]
    fields, get_settings, update_settings = builder(bot)
    domain_view = DomainSettingsView(
        title=title,
        fields=fields,
        get_settings=get_settings,
        update_settings=update_settings,
        on_back=_back_to_main_menu,
    )
    settings = await get_settings(interaction.guild_id)
    from views.settings_panel import build_domain_embed

    await interaction.response.edit_message(
        content=None, embed=build_domain_embed(title, fields, settings), view=domain_view
    )


async def _back_to_main_menu(interaction: discord.Interaction) -> None:
    await interaction.response.edit_message(
        content=None, embed=main_menu_embed(), view=MainConfigMenuView()
    )


def main_menu_embed() -> discord.Embed:
    embed = discord.Embed(
        title="⚙️ Central de Configuração",
        description="Selecione uma categoria abaixo pra configurar o bot.",
    )
    return embed


class _CategorySelect(discord.ui.Select["MainConfigMenuView"]):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(label="🎫 Tickets", value="tickets"),
            discord.SelectOption(label="👮 Cargos", value="cargos"),
            discord.SelectOption(label="🔐 Permissões", value="permissoes"),
            discord.SelectOption(label="📊 Dashboard", value="dashboard"),
            discord.SelectOption(label="📈 Ranking", value="ranking"),
            discord.SelectOption(label="⭐ Avaliações", value="avaliacoes"),
            discord.SelectOption(label="🚫 Anti-Spam", value="antispam"),
            discord.SelectOption(label="📋 Auditoria", value="auditoria"),
            discord.SelectOption(label="🔔 Alertas", value="alertas"),
            discord.SelectOption(label="⚙️ Geral", value="geral"),
        ]
        super().__init__(placeholder="Escolha uma categoria...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        await _open_category(interaction, self.values[0])


class _BackToMainMenuButton(discord.ui.Button[Any]):
    def __init__(self) -> None:
        super().__init__(label="◀ Menu principal", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        await _back_to_main_menu(interaction)


class MainConfigMenuView(discord.ui.View):
    """Menu principal da central de configuração. Nao-persistente (timeout=300)."""

    def __init__(self) -> None:
        super().__init__(timeout=300)
        self.add_item(_CategorySelect())
