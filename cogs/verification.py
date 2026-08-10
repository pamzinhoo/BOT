from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.bot import LimerenceBot
from core.logger import get_logger
from utils.checks import is_staff
from views.verification_view import send_verification_prompt

logger = get_logger("verification")

_SWEEP_INTERVAL_MINUTES = 1
# discord.py despacha cada on_member_join como uma task independente, sem
# nenhum controle de concorrencia entre elas — uma rajada de entradas (raid,
# convite grande) dispara start_verification (add_roles + sessao no banco +
# auditoria + DM) pra todos os membros ao mesmo tempo, competindo pelo mesmo
# pool de conexoes compartilhado com o resto do bot e a API. O semaforo
# limita quantas entradas sao processadas em paralelo sem bloquear o
# recebimento do evento em si (so atrasa o processamento, nunca falha).
_MAX_CONCURRENT_JOINS = 10


class VerificationCog(commands.Cog):
    """Sistema de verificação/CAPTCHA de novos membros (/config -> Verificação)."""

    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot
        self._join_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_JOINS)
        self.sweep_expired_verifications.start()

    def cog_unload(self) -> None:
        self.sweep_expired_verifications.cancel()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        async with self._join_semaphore:
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

    @app_commands.command(
        name="aprovar_verificacao",
        description="Aprova manualmente a verificação de um membro (ex.: ganhou cargo com o bot offline).",
    )
    @app_commands.describe(usuario="Membro a aprovar")
    @is_staff()
    async def aprovar_verificacao(
        self, interaction: discord.Interaction, usuario: discord.Member
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        _, message = await self.bot.verification_service.approve_manually(
            usuario, moderator_id=interaction.user.id, moderator_name=str(interaction.user)
        )
        await interaction.followup.send(message, ephemeral=True)


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(VerificationCog(bot))
