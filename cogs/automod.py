from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.bot import LimerenceBot
from core.logger import get_logger
from database.models.automod import AutoModCategory, AutoModRiskLevel
from services.automod_service import AutoModError
from utils.checks import is_admin
from views.embeds import automod_log_list_embed, automod_status_embed, automod_word_list_embed

logger = get_logger("automod")

_CATEGORY_CHOICES = [
    app_commands.Choice(name="Ofensa", value=AutoModCategory.OFENSA.value),
    app_commands.Choice(name="Discriminação", value=AutoModCategory.DISCRIMINACAO.value),
    app_commands.Choice(name="Golpe/Spam", value=AutoModCategory.GOLPE_SPAM.value),
    app_commands.Choice(name="Conteúdo sexual ilegal", value=AutoModCategory.SEXUAL_ILEGAL.value),
    app_commands.Choice(name="Privacidade", value=AutoModCategory.PRIVACIDADE.value),
    app_commands.Choice(name="Ameaça/Assédio", value=AutoModCategory.AMEACA_ASSEDIO.value),
    app_commands.Choice(name="Personalizada", value=AutoModCategory.PERSONALIZADA.value),
]

_LEVEL_CHOICES = [
    app_commands.Choice(name="Baixo", value=AutoModRiskLevel.BAIXO.value),
    app_commands.Choice(name="Médio", value=AutoModRiskLevel.MEDIO.value),
    app_commands.Choice(name="Alto", value=AutoModRiskLevel.ALTO.value),
]


class AutoModCog(commands.Cog):
    automod_group = app_commands.Group(
        name="automod", description="Sistema de moderação automática de mensagens."
    )

    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        try:
            await self.bot.automod_service.evaluate_message(message)
        except discord.Forbidden:
            logger.warning(
                "AutoMod sem permissão para agir na guild %s.", message.guild.id if message.guild else "?"
            )
        except Exception:
            logger.exception("Falha ao avaliar mensagem no AutoMod.")

    @automod_group.command(name="ativar", description="Ativa ou desativa o AutoMod neste servidor.")
    @app_commands.describe(estado="Ligar ou desligar o sistema")
    @app_commands.choices(
        estado=[
            app_commands.Choice(name="Ligar", value="on"),
            app_commands.Choice(name="Desligar", value="off"),
        ]
    )
    @is_admin()
    async def ativar(self, interaction: discord.Interaction, estado: app_commands.Choice[str]) -> None:
        if interaction.guild is None:
            return
        await interaction.response.defer(ephemeral=True)
        enabled = estado.value == "on"
        settings = await self.bot.automod_service.set_enabled(interaction.guild.id, enabled)
        await interaction.followup.send(
            f"AutoMod {'ativado' if settings.enabled else 'desativado'} neste servidor.", ephemeral=True
        )

    @automod_group.command(name="adicionar", description="Adiciona uma palavra/expressão personalizada à lista bloqueada.")
    @app_commands.describe(
        palavra="Palavra ou expressão a bloquear",
        categoria="Categoria da palavra",
        nivel="Nível de risco (define a ação automática)",
    )
    @app_commands.choices(categoria=_CATEGORY_CHOICES, nivel=_LEVEL_CHOICES)
    @is_admin()
    async def adicionar(
        self,
        interaction: discord.Interaction,
        palavra: str,
        categoria: app_commands.Choice[str] | None = None,
        nivel: app_commands.Choice[str] | None = None,
    ) -> None:
        if interaction.guild is None:
            return
        await interaction.response.defer(ephemeral=True)
        try:
            word = await self.bot.automod_service.add_word(
                interaction.guild.id,
                palavra,
                categoria=AutoModCategory(categoria.value) if categoria else AutoModCategory.PERSONALIZADA,
                nivel=AutoModRiskLevel(nivel.value) if nivel else AutoModRiskLevel.BAIXO,
                added_by_id=interaction.user.id,
            )
        except AutoModError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return
        await interaction.followup.send(
            f"✅ Palavra **{word.palavra}** adicionada (categoria: {word.categoria.value}, "
            f"nível: {word.nivel.value}).",
            ephemeral=True,
        )

    @automod_group.command(name="remover", description="Remove uma palavra da lista bloqueada.")
    @app_commands.describe(palavra="Palavra ou expressão a remover")
    @is_admin()
    async def remover(self, interaction: discord.Interaction, palavra: str) -> None:
        if interaction.guild is None:
            return
        await interaction.response.defer(ephemeral=True)
        removed = await self.bot.automod_service.remove_word(interaction.guild.id, palavra)
        if removed:
            await interaction.followup.send(f"✅ Palavra **{palavra}** removida.", ephemeral=True)
        else:
            await interaction.followup.send("❌ Palavra não encontrada.", ephemeral=True)

    @automod_group.command(name="lista", description="Mostra as palavras atualmente bloqueadas.")
    @is_admin()
    async def lista(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        await interaction.response.defer(ephemeral=True)
        words = await self.bot.automod_service.list_effective_words(interaction.guild.id)
        await interaction.followup.send(embed=automod_word_list_embed(words), ephemeral=True)

    @automod_group.command(name="configurar", description="Configura as punições e exceções do AutoMod.")
    @app_commands.describe(
        timeout_medio_minutos="Duração do timeout para infrações de médio risco",
        timeout_alto_minutos="Duração do timeout para infrações de alto risco (ignorado se usar_ban=Sim)",
        usar_ban_alto_risco="Se Sim, bane em vez de aplicar timeout no alto risco",
        canal_alerta="Canal onde o AutoMod avisa a staff em infrações de alto risco",
        canal_ignorado="Canal onde o AutoMod não age",
        cargo_ignorado="Cargo que o AutoMod ignora (ex.: staff)",
    )
    @is_admin()
    async def configurar(
        self,
        interaction: discord.Interaction,
        timeout_medio_minutos: int | None = None,
        timeout_alto_minutos: int | None = None,
        usar_ban_alto_risco: bool | None = None,
        canal_alerta: discord.TextChannel | None = None,
        canal_ignorado: discord.TextChannel | None = None,
        cargo_ignorado: discord.Role | None = None,
    ) -> None:
        if interaction.guild is None:
            return
        # Defere de imediato: get_settings + update_settings abaixo sao
        # chamadas ao banco que podem passar dos 3s de prazo do Discord
        # antes da 1a resposta.
        await interaction.response.defer(ephemeral=True)
        settings = await self.bot.automod_service.get_settings(interaction.guild.id)
        fields: dict[str, object] = {}
        if timeout_medio_minutos is not None:
            fields["medio_timeout_minutes"] = timeout_medio_minutos
        if timeout_alto_minutos is not None:
            fields["alto_timeout_minutes"] = timeout_alto_minutos
        if usar_ban_alto_risco is not None:
            fields["alto_use_ban"] = usar_ban_alto_risco
        if canal_alerta is not None:
            fields["alert_channel_id"] = canal_alerta.id
        if canal_ignorado is not None:
            ignored = list(settings.ignored_channel_ids)
            if canal_ignorado.id not in ignored:
                ignored.append(canal_ignorado.id)
            fields["ignored_channel_ids"] = ignored
        if cargo_ignorado is not None:
            ignored_roles = list(settings.ignored_role_ids)
            if cargo_ignorado.id not in ignored_roles:
                ignored_roles.append(cargo_ignorado.id)
            fields["ignored_role_ids"] = ignored_roles

        if not fields:
            await interaction.followup.send(embed=automod_status_embed(settings), ephemeral=True)
            return

        settings = await self.bot.automod_service.update_settings(interaction.guild.id, **fields)
        await interaction.followup.send(embed=automod_status_embed(settings), ephemeral=True)

    @automod_group.command(name="logs", description="Mostra o histórico de ações automáticas do AutoMod.")
    @app_commands.describe(quantidade="Quantidade de registros (padrão 20)")
    @is_admin()
    async def logs(self, interaction: discord.Interaction, quantidade: int = 20) -> None:
        if interaction.guild is None:
            return
        await interaction.response.defer(ephemeral=True)
        entries = await self.bot.automod_service.list_logs(interaction.guild.id, min(quantidade, 50))
        await interaction.followup.send(embed=automod_log_list_embed(entries), ephemeral=True)


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(AutoModCog(bot))
