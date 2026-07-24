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
        ticket = await self.bot.ticket_service.get_by_channel_id(message.channel.id)
        if ticket is None:
            return
        is_staff = message.author.id != ticket.opened_by_discord_id
        await self.bot.ticket_service.record_first_message(message, is_staff)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        await self.bot.ticket_service.mark_deleted_before_service(channel.id)


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(TicketsCog(bot))
