from __future__ import annotations

import discord
from discord.ext import commands, tasks

from core.bot import LimerenceBot
from core.logger import get_logger
from views.verification_view import send_verification_prompt

logger = get_logger("verification")

_SWEEP_INTERVAL_MINUTES = 1


class VerificationCog(commands.Cog):
    """Sistema de verificação/CAPTCHA de novos membros (/config -> Verificação)."""

    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot
        self.sweep_expired_verifications.start()

    def cog_unload(self) -> None:
        self.sweep_expired_verifications.cancel()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        try:
            prompt = await self.bot.verification_service.start_verification(member)
        except Exception:
            logger.exception(
                "Falha ao iniciar verificação para %s na guild %s.", member.id, member.guild.id
            )
            return
        if prompt is None:
            return
        await send_verification_prompt(self.bot, member, prompt)

    @tasks.loop(minutes=_SWEEP_INTERVAL_MINUTES)
    async def sweep_expired_verifications(self) -> None:
        try:
            count = await self.bot.verification_service.sweep_expired()
            if count:
                logger.info("Verificações expiradas processadas: %d", count)
        except Exception:
            logger.exception("Falha ao varrer verificações expiradas.")

    @sweep_expired_verifications.before_loop
    async def _before_loop(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(VerificationCog(bot))
