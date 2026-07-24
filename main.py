from __future__ import annotations

import asyncio

import discord

from config.settings import SettingsError, get_settings
from core.bot import LimerenceBot
from core.logger import get_logger, setup_logging
from database.database import init_database


async def main() -> None:
    try:
        settings = get_settings()
    except SettingsError as exc:
        print(f"Erro de configuracao: {exc}")
        raise SystemExit(1) from exc

    setup_logging(settings.log_level)
    logger = get_logger("main")

    database = init_database(settings.database_url, echo=False)
    bot = LimerenceBot(settings=settings, database=database)

    try:
        logger.info("Iniciando BOT LIMERENCE (ambiente: %s)...", settings.environment)
        await bot.start(settings.discord_token)
    except discord.LoginFailure:
        logger.critical("Falha no login: DISCORD_TOKEN invalido.")
    finally:
        if not bot.is_closed():
            await bot.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot encerrado pelo usuario.")
