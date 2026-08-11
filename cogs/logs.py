from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.bot import LimerenceBot
from database.repositories.log_repository import LogRepository
from utils.checks import is_staff
from utils.constants import EMBED_COLOR_DEFAULT, LOG_ACTION_LABELS


class LogsCog(commands.Cog):
    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot

    @app_commands.command(name="logs", description="Mostra as últimas entradas de auditoria.")
    @is_staff()
    async def logs(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            return
        await interaction.response.defer(ephemeral=True)
        async with self.bot.database.session() as session:
            entries = await LogRepository(session).list_recent(interaction.guild_id, limit=10)

        if not entries:
            await interaction.followup.send("Nenhum log registrado ainda.", ephemeral=True)
            return

        lines = [
            f"`{entry.created_at:%d/%m %H:%M}` **{LOG_ACTION_LABELS[entry.action]}** — {entry.message}"
            for entry in entries
        ]
        embed = discord.Embed(
            title="📜 Logs recentes", description="\n".join(lines), color=EMBED_COLOR_DEFAULT
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(LogsCog(bot))
