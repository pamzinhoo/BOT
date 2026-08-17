from __future__ import annotations

import discord
from discord.ext import commands

from core.bot import LimerenceBot
from core.logger import get_logger

logger = get_logger("guild_registry")


class GuildRegistryCog(commands.Cog):
    """Mantem a tabela `guilds` (registro de tenant) em dia: cria/reativa no
    join, marca inativa na saida, sincroniza tudo uma vez ao conectar (cobre
    guilds em que o bot ja estava mas nunca tinham sido registradas)."""

    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot
        # on_ready do discord.py dispara a cada RESUME/reconexao do gateway,
        # nao so no boot frio — sem essa guarda, rede instavel faz o bot
        # reprocessar (ensure_guild = 1-2 round-trips) TODAS as guilds a
        # cada reconexao. So precisa rodar uma vez por processo: cobre
        # guilds que o bot ja estava mas nunca tinham sido registradas;
        # entrada/saida depois disso ja e tratada por on_guild_join/remove.
        self._synced_once = False

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._synced_once:
            return
        self._synced_once = True
        for guild in self.bot.guilds:
            try:
                await self.bot.guild_service.ensure_guild(guild)
            except Exception:
                logger.exception("Falha ao registrar guild %s no startup.", guild.id)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        try:
            await self.bot.guild_service.ensure_guild(guild)
        except Exception:
            logger.exception("Falha ao registrar guild %s no join.", guild.id)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        try:
            await self.bot.guild_service.mark_inactive(guild.id)
        except Exception:
            logger.exception("Falha ao marcar guild %s como inativa.", guild.id)


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(GuildRegistryCog(bot))
