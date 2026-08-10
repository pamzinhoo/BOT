from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.bot import LimerenceBot
from services.ranking_service import RankingPeriod
from utils.checks import has_permission
from views.embeds import ranking_embed

_PERIOD_CHOICES = [
    app_commands.Choice(name="Hoje", value=RankingPeriod.DAILY.value),
    app_commands.Choice(name="Semana", value=RankingPeriod.WEEKLY.value),
    app_commands.Choice(name="Mês", value=RankingPeriod.MONTHLY.value),
    app_commands.Choice(name="Geral", value=RankingPeriod.ALLTIME.value),
]


class RankingCog(commands.Cog):
    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot

    @app_commands.command(name="ranking", description="Mostra o ranking da staff de suporte.")
    @app_commands.describe(periodo="Período do ranking (padrão: geral).")
    @app_commands.choices(periodo=_PERIOD_CHOICES)
    @has_permission("ranking")
    async def ranking(
        self, interaction: discord.Interaction, periodo: app_commands.Choice[str] | None = None
    ) -> None:
        if interaction.guild_id is None:
            return
        await interaction.response.defer()
        if periodo is not None:
            period = RankingPeriod(periodo.value)
            label = periodo.name
        else:
            ranking_settings = await self.bot.config_service.get_ranking_settings(interaction.guild_id)
            period = RankingPeriod(ranking_settings.default_period)
            label = next(
                (c.name for c in _PERIOD_CHOICES if c.value == period.value), "Geral"
            )
        entries = await self.bot.ranking_service.compute(interaction.guild_id, period)
        await interaction.followup.send(embed=ranking_embed(entries, label))


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(RankingCog(bot))
