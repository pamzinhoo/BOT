from __future__ import annotations

import discord
from discord.ext import commands

from core.bot import LimerenceBot
from core.logger import get_logger

logger = get_logger("boosters")


class BoostersCog(commands.Cog):
    """Deteccao oficial de boost via evento on_member_update (member.premium_since),
    nunca via mensagens automaticas do Discord. Toda a logica de negocio vive em
    BoosterService — esta Cog so ouve o evento e delega."""

    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.premium_since == after.premium_since:
            return

        try:
            if before.premium_since is None and after.premium_since is not None:
                await self.bot.booster_service.handle_boost_started(after)
            elif before.premium_since is not None and after.premium_since is None:
                await self.bot.booster_service.handle_boost_removed(after)
        except Exception:
            logger.exception("Falha ao processar mudança de boost na guild %s.", after.guild.id)


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(BoostersCog(bot))
