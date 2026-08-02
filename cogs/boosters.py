from __future__ import annotations

import discord
from discord.ext import commands, tasks

from core.bot import LimerenceBot
from core.logger import get_logger

logger = get_logger("boosters")


class BoostersCog(commands.Cog):
    """Deteccao oficial de boost via evento on_member_update (member.premium_since),
    nunca via mensagens automaticas do Discord. Toda a logica de negocio vive em
    BoosterService — esta Cog so ouve o evento e delega. Uma varredura horaria
    complementa o evento pra cobrir boosts que comecaram/terminaram enquanto o
    bot estava offline (deploy, crash, gap de resume do gateway)."""

    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot
        self.reconcile_boosters.start()

    def cog_unload(self) -> None:
        self.reconcile_boosters.cancel()

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

    @tasks.loop(hours=1)
    async def reconcile_boosters(self) -> None:
        for guild in self.bot.guilds:
            try:
                await self.bot.booster_service.reconcile_guild(guild)
            except Exception:
                logger.exception("Falha ao reconciliar boosters na guild %s.", guild.id)

    @reconcile_boosters.before_loop
    async def before_reconcile_boosters(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(BoostersCog(bot))
