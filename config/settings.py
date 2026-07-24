from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

_VALID_ENVIRONMENTS = {"development", "production"}
_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class SettingsError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SettingsError(f"Variavel de ambiente obrigatoria ausente: {name}")
    return value


def _optional_int(name: str) -> int | None:
    value = os.getenv(name)
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise SettingsError(
            f"Variavel de ambiente {name} deve ser um inteiro, recebido: {value!r}"
        ) from exc


@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str
    database_url: str
    environment: str
    log_level: str
    discord_application_id: int | None = field(default=None)
    test_guild_id: int | None = field(default=None)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @classmethod
    def load(cls) -> Settings:
        environment = os.getenv("ENVIRONMENT", "development").strip().lower()
        if environment not in _VALID_ENVIRONMENTS:
            raise SettingsError(
                f"ENVIRONMENT invalido: {environment!r}. Use um de: {sorted(_VALID_ENVIRONMENTS)}"
            )

        log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
        if log_level not in _VALID_LOG_LEVELS:
            raise SettingsError(
                f"LOG_LEVEL invalido: {log_level!r}. Use um de: {sorted(_VALID_LOG_LEVELS)}"
            )

        database_url = _require("DATABASE_URL")
        if not database_url.startswith("postgresql+asyncpg://"):
            raise SettingsError(
                "DATABASE_URL deve usar o driver assincrono: postgresql+asyncpg://..."
            )

        return cls(
            discord_token=_require("DISCORD_TOKEN"),
            database_url=database_url,
            environment=environment,
            log_level=log_level,
            discord_application_id=_optional_int("DISCORD_APPLICATION_ID"),
            test_guild_id=_optional_int("TEST_GUILD_ID"),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.load()
