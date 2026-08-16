from __future__ import annotations

import discord
from discord.ext import commands

from core.bot import LimerenceBot


class TicketsCog(commands.Cog):
    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        # record_first_message_for_channel resolve "e ticket?" + grava a
        # primeira mensagem numa unica consulta/sessao (antes eram duas
        # chamadas separadas a get_by_channel_id) e usa cache negativo pra
        # sair sem bater no banco em canais que ja foram confirmados como
        # "nao e ticket" — a maioria das mensagens do servidor.
        await self.bot.ticket_service.record_first_message_for_channel(message)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        await self.bot.ticket_service.mark_deleted_before_service(channel.id)
        self.bot.ticket_service.forget_channel(channel.id)


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(TicketsCog(bot))
