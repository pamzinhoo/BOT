from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from cogs.guild_registry import GuildRegistryCog


def _bot_with_guilds(n: int) -> MagicMock:
    bot = MagicMock()
    bot.guilds = [MagicMock(id=i) for i in range(n)]
    bot.guild_service.ensure_guild = AsyncMock()
    return bot


async def test_on_ready_ensures_every_guild_first_time() -> None:
    bot = _bot_with_guilds(3)
    cog = GuildRegistryCog(bot)

    await cog.on_ready()

    assert bot.guild_service.ensure_guild.await_count == 3


async def test_on_ready_does_not_reprocess_on_gateway_reconnect() -> None:
    """on_ready dispara a cada RESUME do gateway, nao so no boot frio — a
    segunda chamada (reconexao) nao pode reprocessar todas as guilds de
    novo."""
    bot = _bot_with_guilds(3)
    cog = GuildRegistryCog(bot)

    await cog.on_ready()
    await cog.on_ready()
    await cog.on_ready()

    assert bot.guild_service.ensure_guild.await_count == 3  # so a 1a chamada contou


async def test_on_guild_join_still_works_after_initial_sync() -> None:
    """on_guild_join continua funcionando normalmente — a guarda e so pro
    loop de on_ready, nao afeta entrada de guild nova."""
    bot = _bot_with_guilds(1)
    cog = GuildRegistryCog(bot)
    await cog.on_ready()

    new_guild = MagicMock(id=999)
    await cog.on_guild_join(new_guild)

    assert bot.guild_service.ensure_guild.await_count == 2
