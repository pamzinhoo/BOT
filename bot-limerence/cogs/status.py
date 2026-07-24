from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.bot import LimerenceBot
from services.ranking_service import RankingPeriod
from utils.constants import EMBED_COLOR_DEFAULT


class StatusCog(commands.Cog):
    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot

    @app_commands.command(name="status", description="Overview do servidor de suporte.")
    async def status(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            return
        guild_id = interaction.guild_id

        open_tickets = await self.bot.ticket_service.list_open_by_guild(guild_id)
        ranking = await self.bot.ranking_service.compute(guild_id, RankingPeriod.ALLTIME)

        active_staff_ids = {
            ticket.claimed_by_staff_id for ticket in open_tickets if ticket.claimed_by_staff_id
        }
        assumed = sum(1 for ticket in open_tickets if ticket.claimed_by_staff_id is not None)
        avg_rating = (
            sum(entry.avaliacao_media for entry in ranking) / len(ranking) if ranking else 0.0
        )

        embed = discord.Embed(title="📊 Status do Suporte", color=EMBED_COLOR_DEFAULT)
        embed.add_field(name="👥 Staff Ativos", value=str(len(active_staff_ids)))
        embed.add_field(name="🎫 Tickets Abertos", value=str(len(open_tickets)))
        embed.add_field(name="🎫 Tickets Assumidos", value=str(assumed))
        embed.add_field(name="⭐ Média Geral", value=f"{avg_rating:.1f}")
        await interaction.response.send_message(embed=embed)


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(StatusCog(bot))
