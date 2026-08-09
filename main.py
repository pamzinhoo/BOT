from __future__ import annotations

import asyncio

import discord
import uvicorn

from api.main import create_app
from config.settings import SettingsError, get_settings
from core.bot import LimerenceBot
from core.logger import get_logger, setup_logging
from database.database import init_database


_MAX_LOGIN_RETRIES = 5
_BASE_BACKOFF_SECONDS = 30


async def _start_bot_with_retry(bot: LimerenceBot, token: str, logger) -> None:
    """discord.py nao trata 429 de login como rate limit normal (aquele e
    tratado internamente) — um 429 na PROPRIA chamada de login (ex.: Cloudflare
    bloqueando por excesso de tentativas de conexao em pouco tempo, comum apos
    varios redeploys seguidos) sobe como HTTPException e derruba o processo
    inteiro. Sem esse retry, Render reinicia o processo imediatamente apos o
    crash, o que bate no Discord de novo enquanto o bloqueio ainda esta ativo
    e gera um loop de deploys falhando em sequencia."""
    for attempt in range(1, _MAX_LOGIN_RETRIES + 1):
        try:
            await bot.start(token)
            return
        except discord.HTTPException as exc:
            if exc.status != 429 or attempt == _MAX_LOGIN_RETRIES:
                raise
            wait = _BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                "Login rate limited pelo Discord (429), tentativa %s/%s. Aguardando %ss...",
                attempt, _MAX_LOGIN_RETRIES, wait,
            )
            await asyncio.sleep(wait)


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

    api_app = create_app(bot)
    api_server = uvicorn.Server(
        uvicorn.Config(
            api_app, host=settings.api_host, port=settings.api_port,
            log_level=settings.log_level.lower(),
        )
    )

    try:
        logger.info("Iniciando BOT LIMERENCE (ambiente: %s)...", settings.environment)
        await asyncio.gather(
            _start_bot_with_retry(bot, settings.discord_token, logger),
            api_server.serve(),
        )
    except discord.LoginFailure:
        logger.critical("Falha no login: DISCORD_TOKEN invalido.")
    finally:
        if not bot.is_closed():
            await bot.close()
        api_server.should_exit = True


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot encerrado pelo usuario.")
