from __future__ import annotations

import io
import json

import discord
from discord import app_commands
from discord.ext import commands

from core.bot import LimerenceBot
from services.config_transfer_service import (
    IMPORT_SECTIONS,
    ConfigImportError,
    build_import_plan,
    build_preview_embed,
    export_guild_config,
)
from utils.checks import has_permission, is_owner_or_ceo
from views.audit_log_panel_view import AuditLogPanelView, audit_log_summary_embed
from views.config_history_view import (
    CONFIG_HISTORY_CATEGORY_CHOICES,
    CONFIG_HISTORY_PERIOD_CHOICES,
    ConfigHistoryFilters,
    ConfigHistoryView,
    render_config_history,
)
from views.config_import_view import ConfigImportConfirmView
from views.config_reset_view import ConfigResetAllConfirmView, reset_all_warning_embed
from views.master_config_view import MainConfigMenuView, main_menu_embed


def _fmt_channel(channel_id: int | None) -> str:
    return f"<#{channel_id}>" if channel_id else "—"


def _fmt_role(role_id: int | None) -> str:
    return f"<@&{role_id}>" if role_id else "—"


class ConfigCog(commands.Cog):
    config_group = app_commands.Group(
        name="config", description="Configurações do bot para este servidor."
    )

    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot

    async def _log(
        self,
        interaction: discord.Interaction,
        *,
        category: str,
        name: str,
        before: str,
        after: str,
    ) -> None:
        assert interaction.guild_id is not None
        await self.bot.audit_log_service.record_config_change(
            guild_id=interaction.guild_id,
            actor_id=interaction.user.id,
            actor_name=str(interaction.user),
            config_category=category,
            config_name=name,
            old_value=before,
            new_value=after,
        )

    @config_group.command(
        name="painel",
        description="Abre a central de configuração do bot.",
    )
    @has_permission("config")
    async def painel(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        await interaction.response.send_message(
            embed=main_menu_embed(), view=MainConfigMenuView(), ephemeral=True
        )

    @config_group.command(name="canal-log", description="Define o canal de logs de auditoria.")
    @has_permission("config")
    async def canal_log(self, interaction: discord.Interaction, canal: discord.TextChannel) -> None:
        assert interaction.guild_id is not None
        await interaction.response.defer(ephemeral=True)
        before = await self.bot.config_service.get_settings(interaction.guild_id)
        await self.bot.config_service.update(interaction.guild_id, log_channel_id=canal.id)
        await self._log(
            interaction, category="Tickets", name="Canal de Logs",
            before=_fmt_channel(before.log_channel_id), after=canal.mention,
        )
        await interaction.followup.send(f"Canal de logs definido: {canal.mention}", ephemeral=True)

    @config_group.command(name="canal-ranking", description="Define o canal de ranking.")
    @has_permission("config")
    async def canal_ranking(
        self, interaction: discord.Interaction, canal: discord.TextChannel
    ) -> None:
        assert interaction.guild_id is not None
        await interaction.response.defer(ephemeral=True)
        before = await self.bot.config_service.get_settings(interaction.guild_id)
        await self.bot.config_service.update(
            interaction.guild_id, ranking_channel_id=canal.id, ranking_message_id=None
        )
        await self._log(
            interaction, category="Ranking", name="Canal",
            before=_fmt_channel(before.ranking_channel_id), after=canal.mention,
        )
        await self.bot.painel_service.refresh_dashboard(interaction.guild_id)
        await interaction.followup.send(
            f"Canal de ranking definido: {canal.mention}. A mensagem de ranking foi publicada lá "
            "e vai se atualizar sozinha a cada claim/fechamento/avaliação.",
            ephemeral=True,
        )

    @config_group.command(name="canal-avaliacoes", description="Define o canal de avaliações.")
    @has_permission("config")
    async def canal_avaliacoes(
        self, interaction: discord.Interaction, canal: discord.TextChannel
    ) -> None:
        assert interaction.guild_id is not None
        await interaction.response.defer(ephemeral=True)
        before = await self.bot.config_service.get_settings(interaction.guild_id)
        await self.bot.config_service.update(interaction.guild_id, evaluations_channel_id=canal.id)
        await self._log(
            interaction, category="Avaliações", name="Canal",
            before=_fmt_channel(before.evaluations_channel_id), after=canal.mention,
        )
        await interaction.followup.send(
            f"Canal de avaliações definido: {canal.mention}", ephemeral=True
        )

    @config_group.command(
        name="canal-transcricao",
        description="Define o canal onde as transcrições dos tickets fechados são enviadas.",
    )
    @has_permission("config")
    async def canal_transcricao(
        self, interaction: discord.Interaction, canal: discord.TextChannel
    ) -> None:
        assert interaction.guild_id is not None
        await interaction.response.defer(ephemeral=True)
        before = await self.bot.config_service.get_settings(interaction.guild_id)
        await self.bot.config_service.update(interaction.guild_id, transcript_channel_id=canal.id)
        await self._log(
            interaction, category="Tickets", name="Canal de Transcrição",
            before=_fmt_channel(before.transcript_channel_id), after=canal.mention,
        )
        await interaction.followup.send(
            f"Canal de transcrições definido: {canal.mention}", ephemeral=True
        )

    @config_group.command(
        name="canal-alerta-tickets",
        description="Define o canal onde a staff é avisada quando um ticket novo é aberto.",
    )
    @has_permission("config")
    async def canal_alerta_tickets(
        self, interaction: discord.Interaction, canal: discord.TextChannel
    ) -> None:
        assert interaction.guild_id is not None
        await interaction.response.defer(ephemeral=True)
        before = await self.bot.config_service.get_settings(interaction.guild_id)
        await self.bot.config_service.update(interaction.guild_id, ticket_alert_channel_id=canal.id)
        await self._log(
            interaction, category="Alertas", name="Canal de Alerta de Tickets",
            before=_fmt_channel(before.ticket_alert_channel_id), after=canal.mention,
        )
        await interaction.followup.send(
            f"Canal de alerta de tickets definido: {canal.mention}", ephemeral=True
        )

    @config_group.command(
        name="categoria-ticket", description="Define a categoria onde os tickets são criados."
    )
    @has_permission("config")
    async def categoria_ticket(
        self, interaction: discord.Interaction, categoria: discord.CategoryChannel
    ) -> None:
        assert interaction.guild_id is not None
        await interaction.response.defer(ephemeral=True)
        before = await self.bot.config_service.get_settings(interaction.guild_id)
        await self.bot.config_service.update(interaction.guild_id, ticket_category_id=categoria.id)
        await self._log(
            interaction, category="Tickets", name="Categoria de Tickets",
            before=_fmt_channel(before.ticket_category_id), after=f"<#{categoria.id}>",
        )
        await interaction.followup.send(
            f"Categoria de tickets definida: {categoria.name}", ephemeral=True
        )

    @config_group.command(name="cargo-moderador", description="Define o cargo de moderador.")
    @has_permission("config")
    async def cargo_moderador(self, interaction: discord.Interaction, cargo: discord.Role) -> None:
        assert interaction.guild_id is not None
        await interaction.response.defer(ephemeral=True)
        before = await self.bot.config_service.get_settings(interaction.guild_id)
        await self.bot.config_service.update(interaction.guild_id, moderator_role_id=cargo.id)
        await self._log(
            interaction, category="Cargos", name="Moderador",
            before=_fmt_role(before.moderator_role_id), after=cargo.mention,
        )
        await interaction.followup.send(f"Cargo de moderador definido: {cargo.mention}", ephemeral=True)

    @config_group.command(name="cargo-dev", description="Define o cargo de desenvolvedor.")
    @has_permission("config")
    async def cargo_dev(self, interaction: discord.Interaction, cargo: discord.Role) -> None:
        assert interaction.guild_id is not None
        await interaction.response.defer(ephemeral=True)
        before = await self.bot.config_service.get_settings(interaction.guild_id)
        await self.bot.config_service.update(interaction.guild_id, dev_role_id=cargo.id)
        await self._log(
            interaction, category="Cargos", name="Desenvolvedor",
            before=_fmt_role(before.dev_role_id), after=cargo.mention,
        )
        await interaction.followup.send(f"Cargo de dev definido: {cargo.mention}", ephemeral=True)

    @config_group.command(name="cargo-ceo", description="Define o cargo de CEO.")
    @has_permission("config")
    async def cargo_ceo(self, interaction: discord.Interaction, cargo: discord.Role) -> None:
        assert interaction.guild_id is not None
        await interaction.response.defer(ephemeral=True)
        before = await self.bot.config_service.get_settings(interaction.guild_id)
        await self.bot.config_service.update(interaction.guild_id, ceo_role_id=cargo.id)
        await self._log(
            interaction, category="Cargos", name="CEO",
            before=_fmt_role(before.ceo_role_id), after=cargo.mention,
        )
        await interaction.followup.send(f"Cargo de CEO definido: {cargo.mention}", ephemeral=True)

    @config_group.command(
        name="tempo-inatividade", description="Define minutos para considerar staff inativa."
    )
    @has_permission("config")
    async def tempo_inatividade(self, interaction: discord.Interaction, minutos: int) -> None:
        assert interaction.guild_id is not None
        await interaction.response.defer(ephemeral=True)
        before = await self.bot.config_service.get_settings(interaction.guild_id)
        await self.bot.config_service.update(interaction.guild_id, inactive_after_minutes=minutos)
        await self._log(
            interaction, category="Tickets", name="Tempo de Inatividade",
            before=f"{before.inactive_after_minutes} minutos" if before.inactive_after_minutes else "—",
            after=f"{minutos} minutos",
        )
        await interaction.followup.send(
            f"Tempo de inatividade definido: {minutos} minutos", ephemeral=True
        )

    @config_group.command(
        name="canal-auditoria", description="Define o canal para onde os logs de auditoria são enviados."
    )
    @has_permission("config")
    async def canal_auditoria(
        self, interaction: discord.Interaction, canal: discord.TextChannel
    ) -> None:
        assert interaction.guild_id is not None
        await interaction.response.defer(ephemeral=True)
        before = await self.bot.audit_log_service.get_settings(interaction.guild_id)
        await self.bot.audit_log_service.update_settings(interaction.guild_id, channel_id=canal.id)
        await self._log(
            interaction, category="Auditoria", name="Canal de Auditoria",
            before=_fmt_channel(before.channel_id), after=canal.mention,
        )
        await interaction.followup.send(
            f"Canal de auditoria definido: {canal.mention}", ephemeral=True
        )

    @config_group.command(
        name="auditoria",
        description="Abre um painel pra ativar/desativar categorias de auditoria.",
    )
    @has_permission("config")
    async def auditoria(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        await interaction.response.defer(ephemeral=True)
        settings = await self.bot.audit_log_service.get_settings(interaction.guild_id)
        await interaction.followup.send(
            embed=audit_log_summary_embed(settings), view=AuditLogPanelView(settings), ephemeral=True
        )

    @config_group.command(name="ver", description="Mostra a configuração atual do servidor.")
    @has_permission("config")
    async def ver(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        await interaction.response.defer(ephemeral=True)
        settings = await self.bot.config_service.get_settings(interaction.guild_id)
        embed = discord.Embed(title="⚙️ Configuração atual")
        embed.add_field(name="Canal de Logs", value=f"<#{settings.log_channel_id}>" if settings.log_channel_id else "—")
        embed.add_field(name="Canal de Ranking", value=f"<#{settings.ranking_channel_id}>" if settings.ranking_channel_id else "—")
        embed.add_field(name="Canal de Avaliações", value=f"<#{settings.evaluations_channel_id}>" if settings.evaluations_channel_id else "—")
        embed.add_field(name="Canal de Alerta de Tickets", value=f"<#{settings.ticket_alert_channel_id}>" if settings.ticket_alert_channel_id else "—")
        embed.add_field(name="Canal de Transcrições", value=f"<#{settings.transcript_channel_id}>" if settings.transcript_channel_id else "—")
        embed.add_field(name="Canal do Dashboard", value=f"<#{settings.dashboard_channel_id}>" if settings.dashboard_channel_id else "—")
        embed.add_field(name="Categoria de Tickets", value=f"<#{settings.ticket_category_id}>" if settings.ticket_category_id else "—")
        embed.add_field(name="Cargo Moderador", value=f"<@&{settings.moderator_role_id}>" if settings.moderator_role_id else "—")
        embed.add_field(name="Cargo Dev", value=f"<@&{settings.dev_role_id}>" if settings.dev_role_id else "—")
        embed.add_field(name="Cargo CEO", value=f"<@&{settings.ceo_role_id}>" if settings.ceo_role_id else "—")
        embed.add_field(name="Inatividade", value=f"{settings.inactive_after_minutes} min" if settings.inactive_after_minutes else "—")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @config_group.command(
        name="history", description="Consulta o histórico de alterações feitas via /config."
    )
    @app_commands.describe(
        usuario="Filtrar por quem executou a alteração",
        categoria="Filtrar por categoria da configuração",
        configuracao="Buscar pelo nome da configuração (ex: 'auto close')",
        periodo="Janela de tempo (padrão: tudo)",
    )
    @app_commands.choices(
        categoria=CONFIG_HISTORY_CATEGORY_CHOICES, periodo=CONFIG_HISTORY_PERIOD_CHOICES
    )
    @has_permission("config")
    async def history(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member | None = None,
        categoria: app_commands.Choice[str] | None = None,
        configuracao: str | None = None,
        periodo: app_commands.Choice[str] | None = None,
    ) -> None:
        assert interaction.guild_id is not None
        await interaction.response.defer(ephemeral=True)
        filters = ConfigHistoryFilters(
            usuario_id=usuario.id if usuario else None,
            categoria=categoria.value if categoria else None,
            configuracao=configuracao,
            periodo=periodo.value if periodo else None,
        )
        embed, total_pages = await render_config_history(self.bot, interaction.guild_id, filters)
        await interaction.followup.send(
            embed=embed, view=ConfigHistoryView(filters, total_pages), ephemeral=True
        )

    @config_group.command(
        name="export", description="Exporta a configuração deste servidor em um arquivo JSON."
    )
    @has_permission("config")
    async def export(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            return
        await interaction.response.defer(ephemeral=True)
        data = await export_guild_config(self.bot, guild)
        content = json.dumps(data, indent=2, ensure_ascii=False)
        file = discord.File(io.BytesIO(content.encode("utf-8")), filename=f"config-{guild.id}.json")
        await interaction.followup.send(
            "Configuração exportada. Guarde o arquivo pra importar em outro servidor com `/config import`.",
            file=file,
            ephemeral=True,
        )

    @config_group.command(
        name="import",
        description="Importa uma configuração exportada com /config export (anexe o arquivo .json).",
    )
    @app_commands.describe(
        arquivo="Arquivo .json gerado por /config export",
        secoes="Importar tudo ou só uma categoria (padrão: tudo)",
        simulacao="Modo simulação — só mostra o que mudaria, não aplica nada",
    )
    @app_commands.choices(
        secoes=[app_commands.Choice(name="Tudo", value="tudo")]
        + [app_commands.Choice(name=label, value=value) for value, label in IMPORT_SECTIONS]
    )
    @has_permission("config")
    async def import_(
        self,
        interaction: discord.Interaction,
        arquivo: discord.Attachment,
        secoes: app_commands.Choice[str] | None = None,
        simulacao: bool = False,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            return
        await interaction.response.defer(ephemeral=True)

        try:
            raw_bytes = await arquivo.read()
            data = json.loads(raw_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError, discord.HTTPException):
            await interaction.followup.send("Arquivo inválido — não é um JSON legível.", ephemeral=True)
            return

        section_filter = None if secoes is None or secoes.value == "tudo" else {secoes.value}
        try:
            plan, changes, integrity = await build_import_plan(
                self.bot, guild, data, sections=section_filter
            )
        except ConfigImportError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        if simulacao:
            await interaction.followup.send(
                embed=build_preview_embed(changes, integrity, dry_run=True), ephemeral=True
            )
            return

        view = ConfigImportConfirmView(
            guild.id, plan, changes, interaction.user.id, arquivo.filename, data, integrity
        )
        await interaction.followup.send(
            content="Confira as mudanças antes de aplicar:",
            embed=build_preview_embed(changes, integrity),
            view=view,
            ephemeral=True,
        )

    @config_group.command(
        name="reset-all",
        description="Restaura TODAS as configurações do servidor para o padrão (Owner/CEO apenas).",
    )
    @is_owner_or_ceo()
    async def reset_all(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        await interaction.response.send_message(
            embed=reset_all_warning_embed(),
            view=ConfigResetAllConfirmView(interaction.user.id),
            ephemeral=True,
        )


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(ConfigCog(bot))
