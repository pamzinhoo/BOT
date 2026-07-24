from __future__ import annotations

import time

from discord.ext import commands, tasks

from core.bot import LimerenceBot
from core.logger import get_logger

logger = get_logger("bot_status")

_TICK_MINUTES = 1


class BotStatusCog(commands.Cog):
    """Mantem o painel de status do bot (configurado em /config painel) atualizado,
    editando sempre a mesma mensagem no canal escolhido pela guild."""

    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot
        self._last_refresh: dict[int, float] = {}
        self.auto_update_status.start()

    def cog_unload(self) -> None:
        self.auto_update_status.cancel()

    @tasks.loop(minutes=_TICK_MINUTES)
    async def auto_update_status(self) -> None:
        for status_settings in await self.bot.config_service.list_bot_status_with_channel():
            guild_id = status_settings.guild_id
            now = time.monotonic()
            last = self._last_refresh.get(guild_id, 0.0)
            if now - last < status_settings.update_interval_minutes * 60:
                continue
            self._last_refresh[guild_id] = now
            try:
                await self.bot.bot_status_service.refresh(guild_id)
            except Exception:
                logger.exception("Falha ao atualizar painel de status da guild %s.", guild_id)

    @auto_update_status.before_loop
    async def _before_loop(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(BotStatusCog(bot))
