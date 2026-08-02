from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.bot import LimerenceBot
from utils.checks import member_is_admin, member_is_staff
from views.embeds import help_command_embed, help_main_embed
from views.help_views import HelpMainView


class HelpCog(commands.Cog):
    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="Mostra a central de ajuda do bot.")
    @app_commands.describe(comando="Nome de um comando específico pra ver detalhes (ex.: punir)")
    async def help_command(
        self, interaction: discord.Interaction, comando: str | None = None
    ) -> None:
        is_admin = await member_is_admin(interaction)
        is_staff = await member_is_staff(interaction)

        if comando:
            command = await self.bot.help_service.get_visible_command(
                comando.strip().lower(), is_admin=is_admin, is_staff=is_staff
            )
            if command is None:
                await interaction.response.send_message(
                    "Comando não encontrado (ou você não tem permissão pra vê-lo).", ephemeral=True
                )
                return
            await interaction.response.send_message(embed=help_command_embed(command), ephemeral=True)
            return

        await interaction.response.send_message(
            embed=help_main_embed(), view=HelpMainView(), ephemeral=True
        )

    @help_command.autocomplete("comando")
    async def _comando_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        is_admin = await member_is_admin(interaction)
        is_staff = await member_is_staff(interaction)
        commands_ = await self.bot.help_service.list_all_visible(is_admin=is_admin, is_staff=is_staff)
        current = current.lower()
        return [
            app_commands.Choice(name=c.command_name, value=c.command_name)
            for c in commands_
            if current in c.command_name.lower()
        ][:25]


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(HelpCog(bot))
