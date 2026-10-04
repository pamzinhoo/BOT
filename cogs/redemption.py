from __future__ import annotations

from typing import TYPE_CHECKING

from discord.ext import commands, tasks

from core.logger import get_logger

if TYPE_CHECKING:
    from core.bot import LimerenceBot

logger = get_logger("redemption")


class RedemptionCog(commands.Cog):
    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot
        self.process_redemptions.start()

    def cog_unload(self) -> None:
        self.process_redemptions.cancel()

    @tasks.loop(seconds=60)
    async def process_redemptions(self) -> None:
        try:
            await self.bot.redemption_service.process_pending(self.bot)
        except Exception:
            logger.exception("Falha ao reconciliar resgates.")

    @process_redemptions.before_loop
    async def before_process_redemptions(self) -> None:
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            try:
                await self.bot.painel_service.refresh_shop_panel(guild.id)
            except Exception:
                logger.exception("Falha ao atualizar painel da loja na guild %s.", guild.id)


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(RedemptionCog(bot))
