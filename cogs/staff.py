from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.bot import LimerenceBot
from views.embeds import staff_profile_embed


class StaffCog(commands.Cog):
    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot

    @app_commands.command(name="staff", description="Mostra o perfil e as estatísticas de um membro da staff.")
    @app_commands.checks.cooldown(1, 10.0, key=lambda i: (i.guild_id, i.user.id))
    async def staff(self, interaction: discord.Interaction, membro: discord.Member) -> None:
        if interaction.guild_id is None:
            return
        await interaction.response.defer()
        profile = await self.bot.staff_service.get_profile(interaction.guild_id, membro.id)
        if profile is None:
            await interaction.followup.send(
                "Este membro ainda não possui registro de staff.", ephemeral=True
            )
            return
        await interaction.followup.send(embed=staff_profile_embed(profile, membro))


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(StaffCog(bot))
