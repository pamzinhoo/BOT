from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

_VALID_ENVIRONMENTS = {"development", "production"}
_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_VALID_PAYMENT_MODES = {"sandbox", "production"}


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


def _optional(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value else None


def _bool(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str
    database_url: str
    environment: str
    log_level: str
    discord_application_id: int | None = field(default=None)
    test_guild_id: int | None = field(default=None)

    payment_mode: str = field(default="sandbox")
    public_base_url: str = field(default="")
    api_host: str = field(default="127.0.0.1")
    api_port: int = field(default=8000)
    webhook_enabled: bool = field(default=False)
    mercadopago_access_token_sandbox: str | None = field(default=None)
    mercadopago_access_token_production: str | None = field(default=None)
    mercadopago_public_key_sandbox: str | None = field(default=None)
    mercadopago_public_key_production: str | None = field(default=None)
    mercadopago_webhook_secret_sandbox: str | None = field(default=None)
    mercadopago_webhook_secret_production: str | None = field(default=None)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_payment_sandbox(self) -> bool:
        return self.payment_mode == "sandbox"

    @property
    def mercadopago_access_token(self) -> str | None:
        return (
            self.mercadopago_access_token_sandbox
            if self.is_payment_sandbox
            else self.mercadopago_access_token_production
        )

    @property
    def mercadopago_public_key(self) -> str | None:
        return (
            self.mercadopago_public_key_sandbox
            if self.is_payment_sandbox
            else self.mercadopago_public_key_production
        )

    @property
    def mercadopago_webhook_secret(self) -> str | None:
        return (
            self.mercadopago_webhook_secret_sandbox
            if self.is_payment_sandbox
            else self.mercadopago_webhook_secret_production
        )

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

        payment_mode = os.getenv("PAYMENT_MODE", "sandbox").strip().lower()
        if payment_mode not in _VALID_PAYMENT_MODES:
            raise SettingsError(
                f"PAYMENT_MODE invalido: {payment_mode!r}. Use um de: {sorted(_VALID_PAYMENT_MODES)}"
            )

        api_port = _optional_int("API_PORT") or 8000
        public_base_url = _optional("PUBLIC_BASE_URL") or f"http://localhost:{api_port}"

        webhook_enabled = _bool("WEBHOOK_ENABLED", default=False)
        webhook_secret_production = _optional("MERCADOPAGO_WEBHOOK_SECRET_PRODUCTION")
        if webhook_enabled and payment_mode == "production" and not webhook_secret_production:
            raise SettingsError(
                "MERCADOPAGO_WEBHOOK_SECRET_PRODUCTION ausente com PAYMENT_MODE=production "
                "e WEBHOOK_ENABLED=true — o endpoint de webhook aceitaria notificacoes sem "
                "verificar assinatura. Configure o secret antes de subir em producao."
            )

        return cls(
            discord_token=_require("DISCORD_TOKEN"),
            database_url=database_url,
            environment=environment,
            log_level=log_level,
            discord_application_id=_optional_int("DISCORD_APPLICATION_ID"),
            test_guild_id=_optional_int("TEST_GUILD_ID"),
            payment_mode=payment_mode,
            public_base_url=public_base_url,
            api_host=_optional("API_HOST") or "127.0.0.1",
            api_port=api_port,
            webhook_enabled=webhook_enabled,
            mercadopago_access_token_sandbox=_optional("MERCADOPAGO_ACCESS_TOKEN_SANDBOX"),
            mercadopago_access_token_production=_optional("MERCADOPAGO_ACCESS_TOKEN_PRODUCTION"),
            mercadopago_public_key_sandbox=_optional("MERCADOPAGO_PUBLIC_KEY_SANDBOX"),
            mercadopago_public_key_production=_optional("MERCADOPAGO_PUBLIC_KEY_PRODUCTION"),
            mercadopago_webhook_secret_sandbox=_optional("MERCADOPAGO_WEBHOOK_SECRET_SANDBOX"),
            mercadopago_webhook_secret_production=webhook_secret_production,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.load()
