from __future__ import annotations

import time

import discord
from discord.ext import commands, tasks

from core.bot import LimerenceBot
from core.logger import get_logger

logger = get_logger("subscription_renewal")

# o loop bate de 15 em 15 min; o intervalo real de cada guild vem de
# SubscriptionRenewalSettings.check_interval_hours (1/6/12/24h) — mesma
# estrategia de throttle-por-dict do auto_update_dashboards (cogs/painel.py).
_TICK_MINUTES = 15


class SubscriptionRenewalCog(commands.Cog):
    """Só o wrapper do loop: toda a regra de aviso/carência/expiração vive em
    SubscriptionReminderService (nenhuma lógica de negócio dentro da Cog)."""

    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot
        self._last_check: dict[int, float] = {}
        self.check_subscription_renewals.start()

    def cog_unload(self) -> None:
        self.check_subscription_renewals.cancel()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        # sem isso o dict de throttle so cresce pra sempre (bot saindo/entrando
        # em centenas de servidores ao longo do tempo, uso comercial).
        self._last_check.pop(guild.id, None)

    @tasks.loop(minutes=_TICK_MINUTES)
    async def check_subscription_renewals(self) -> None:
        settings_rows = await self.bot.subscription_renewal_config_service.list_enabled_settings()
        for settings in settings_rows:
            guild_id = settings.guild_id
            now = time.monotonic()
            interval_seconds = max(1, settings.check_interval_hours) * 3600
            last = self._last_check.get(guild_id, 0.0)
            if now - last < interval_seconds:
                continue
            self._last_check[guild_id] = now
            try:
                await self.bot.subscription_reminder_service.run_check_cycle(guild_id)
            except Exception:
                logger.exception(
                    "Falha no ciclo de renovação de assinaturas da guild %s.", guild_id
                )

    @check_subscription_renewals.before_loop
    async def _before_loop(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(SubscriptionRenewalCog(bot))
