from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.bot import LimerenceBot
from core.logger import get_logger
from utils.checks import is_admin
from views.embeds import open_ticket_panel_embed, painel_embed
from views.painel_view import PainelView

logger = get_logger("painel")

_AUTO_UPDATE_TICK_MINUTES = 1


class PainelCog(commands.Cog):
    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot
        self._last_auto_update: dict[int, float] = {}
        self.auto_update_dashboards.start()

    def cog_unload(self) -> None:
        self.auto_update_dashboards.cancel()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        # sem isso o dict de throttle so cresce pra sempre (bot saindo/entrando
        # em centenas de servidores ao longo do tempo, uso comercial).
        self._last_auto_update.pop(guild.id, None)

    @tasks.loop(minutes=_AUTO_UPDATE_TICK_MINUTES)
    async def auto_update_dashboards(self) -> None:
        for dashboard_settings in await self.bot.config_service.list_dashboards_with_auto_update():
            guild_id = dashboard_settings.guild_id
            now = time.monotonic()
            last = self._last_auto_update.get(guild_id, 0.0)
            if now - last < dashboard_settings.update_interval_minutes * 60:
                continue
            self._last_auto_update[guild_id] = now
            try:
                await self.bot.painel_service.refresh_dashboard(guild_id)
            except Exception:
                logger.exception("Falha ao auto-atualizar dashboard da guild %s.", guild_id)

    @auto_update_dashboards.before_loop
    async def _before_loop(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="painel-setup",
        description="Publica neste canal o painel de abertura de tickets (só isso, sem dashboard).",
    )
    @is_admin()
    async def painel_setup(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        channel = interaction.channel
        if guild is None or not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Use este comando em um canal de texto de um servidor.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        await channel.send(embed=open_ticket_panel_embed(), view=PainelView())
        await interaction.followup.send(
            f"Painel de abertura de tickets publicado em {channel.mention}.", ephemeral=True
        )

    @app_commands.command(
        name="dashboard-setup",
        description="Publica neste canal o dashboard ao vivo da staff (tickets abertos + top 5).",
    )
    @is_admin()
    async def dashboard_setup(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        channel = interaction.channel
        if guild is None or not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Use este comando em um canal de texto de um servidor.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        dashboard_message = await channel.send(embed=painel_embed(0, []))
        await self.bot.config_service.update(
            guild.id, dashboard_channel_id=channel.id, dashboard_message_id=dashboard_message.id
        )
        await self.bot.painel_service.refresh_dashboard(guild.id)
        await interaction.followup.send(
            f"Dashboard da staff publicado em {channel.mention}.", ephemeral=True
        )


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(PainelCog(bot))
