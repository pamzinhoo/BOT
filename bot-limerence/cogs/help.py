from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.bot import LimerenceBot

_EMOJI_BY_COMMAND: dict[str, str] = {
    "config": "⚙️",
    "audit": "🕵️",
    "claim": "🙋",
    "unclaim": "🙅",
    "logs": "📜",
    "ranking": "🏆",
    "staff": "📋",
    "status": "📈",
    "painel-setup": "🎫",
    "dashboard-setup": "📊",
    "help": "📖",
}

_FIELD_LIMIT = 1024


def _command_lines(command: app_commands.Command | app_commands.Group) -> list[str]:
    if isinstance(command, app_commands.Group):
        return [f"`/{command.name} {sub.name}` — {sub.description}" for sub in command.commands]
    return [f"`/{command.name}` — {command.description}"]


def _chunk_lines(lines: list[str], limit: int = _FIELD_LIMIT) -> list[str]:
    chunks: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit and current:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def build_help_embed(tree: app_commands.CommandTree) -> discord.Embed:
    embed = discord.Embed(
        title="📖 Comandos do bot",
        description="Tudo que o bot sabe fazer, organizado por área.",
        color=discord.Color.blurple(),
    )
    for command in sorted(tree.get_commands(), key=lambda c: c.name):
        emoji = _EMOJI_BY_COMMAND.get(command.name, "🔹")
        chunks = _chunk_lines(_command_lines(command))
        for i, chunk in enumerate(chunks):
            suffix = f" ({i + 1}/{len(chunks)})" if len(chunks) > 1 else ""
            embed.add_field(name=f"{emoji} /{command.name}{suffix}", value=chunk, inline=False)
    embed.set_footer(text="Use /config painel para configurar o bot neste servidor.")
    return embed


class HelpCog(commands.Cog):
    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot

    @app_commands.command(
        name="help", description="Mostra todos os comandos do bot e o que cada um faz."
    )
    async def help_command(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            embed=build_help_embed(self.bot.tree), ephemeral=True
        )


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(HelpCog(bot))
