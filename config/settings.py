from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

_VALID_ENVIRONMENTS = {"development", "production"}
_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_VALID_PAYMENT_MODES = {"sandbox", "production"}
# HMAC-SHA256 (JWT_SECRET_KEY, INTERNAL_API_SECRET) fica tao forte quanto a
# chave — 32 bytes e o minimo recomendado pra HS256 (RFC 7518 3.2). Abaixo
# disso a assinatura fica forjavel por forca bruta offline (downgrade de
# criptografia por configuracao fraca, nao por codigo).
_MIN_SECRET_LENGTH = 32


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

    # Pool do SQLAlchemy/asyncpg compartilhado entre o bot (Discord) e a API
    # embutida (auth/download/license do Launcher, ver main.py) — as duas
    # coisas rodam no mesmo processo e batem no MESMO Postgres do backend
    # (repo `limerence`). O default implicito do SQLAlchemy (5 + 10 overflow
    # = 15 conexoes) fica curto com uso concorrente pesado; configuravel aqui
    # em vez de fixo no codigo pra poder ajustar conforme o limite real de
    # conexoes do plano do Postgres (Supabase/pooler).
    db_pool_size: int = field(default=10)
    db_max_overflow: int = field(default=20)

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

    discord_oauth_client_id: str = field(default="")
    discord_oauth_client_secret: str = field(default="")
    discord_oauth_redirect_uri: str = field(default="")
    jwt_secret_key: str = field(default="")
    jwt_access_ttl_seconds: int = field(default=900)
    refresh_token_ttl_days: int = field(default=30)

    # storage (download de DLC/base game/binario do Launcher) — R2/S3/B2 sao
    # todos S3-compativeis, entao `storage_provider` e so um rotulo (auditoria/
    # log); quem muda o comportamento de verdade e endpoint/credenciais.
    storage_provider: str = field(default="r2")
    storage_bucket: str | None = field(default=None)
    storage_endpoint_url: str | None = field(default=None)
    storage_region: str = field(default="auto")
    storage_access_key_id: str | None = field(default=None)
    storage_secret_access_key: str | None = field(default=None)
    storage_download_ttl_seconds: int = field(default=600)

    # HMAC compartilhado entre Backend e Bot pro canal interno de eventos de
    # licenca (/internal/*, ver api/routes/internal_routes.py) — mesmo
    # esquema HMAC ja usado pra validar webhook do Mercado Pago
    # (providers/mercadopago.py: validate_webhook), reaproveitado aqui em vez
    # de inventar um segundo mecanismo.
    internal_api_secret: str | None = field(default=None)

    # Reconciliacao de licencas (Fase 4 da auditoria de performance) — sem
    # limite, `asyncio.gather` sobre todas as guilds ao mesmo tempo faria N
    # sessoes de DB + N rajadas de chamadas Discord simultaneas, competindo
    # com o event loop que tambem serve comandos/eventos do bot. Semaforo
    # limita quantas guilds reconciliam em paralelo; timeout evita que uma
    # guild travada (Discord lento, DB lento) prenda o ciclo inteiro.
    reconcile_max_concurrency: int = field(default=5)
    reconcile_guild_timeout_seconds: int = field(default=30)

    # CORS explicito — a API e consumida por Bearer token (Tauri/Launcher),
    # nao por cookie, entao nao ha CSRF classico via navegador; ainda assim
    # o padrao e negar TODA origem (lista vazia) em vez de deixar implicito.
    # So preencha se algum dia existir um frontend web (ex.: painel staff)
    # chamando esta API direto do navegador.
    cors_allowed_origins: tuple[str, ...] = field(default=())

    @property
    def storage_configured(self) -> bool:
        return bool(self.storage_bucket and self.storage_access_key_id and self.storage_secret_access_key)

    @property
    def internal_api_configured(self) -> bool:
        return bool(self.internal_api_secret)

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
        discord_token = _require("DISCORD_TOKEN")
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
        if environment == "production" and not public_base_url.startswith("https://"):
            raise SettingsError(
                f"PUBLIC_BASE_URL={public_base_url!r} nao usa HTTPS com ENVIRONMENT=production — "
                "token, refresh_token e assinatura de webhook trafegariam em texto claro, "
                "vulneraveis a MITM. Configure PUBLIC_BASE_URL com https:// antes de subir em producao."
            )

        discord_oauth_redirect_uri = (
            _optional("DISCORD_OAUTH_REDIRECT_URI") or f"{public_base_url}/auth/discord/callback"
        )

        jwt_secret_key = _require("JWT_SECRET_KEY")
        if len(jwt_secret_key) < _MIN_SECRET_LENGTH:
            raise SettingsError(
                f"JWT_SECRET_KEY tem {len(jwt_secret_key)} bytes — minimo exigido: "
                f"{_MIN_SECRET_LENGTH}. Chave curta e forjavel por forca bruta offline "
                "(assinatura HS256), permitindo emitir access_token falso pra qualquer player."
            )

        internal_api_secret = _optional("INTERNAL_API_SECRET")
        if internal_api_secret is not None and len(internal_api_secret) < _MIN_SECRET_LENGTH:
            raise SettingsError(
                f"INTERNAL_API_SECRET tem {len(internal_api_secret)} bytes — minimo exigido: "
                f"{_MIN_SECRET_LENGTH}. Protege /internal/* (eventos de licenca, reconciliacao); "
                "chave curta permite forjar requisicoes que concedem/removem cargo."
            )

        cors_raw = _optional("CORS_ALLOWED_ORIGINS")
        cors_allowed_origins = tuple(o.strip() for o in cors_raw.split(",") if o.strip()) if cors_raw else ()

        webhook_enabled = _bool("WEBHOOK_ENABLED", default=False)
        webhook_secret_production = _optional("MERCADOPAGO_WEBHOOK_SECRET_PRODUCTION")
        if webhook_enabled and payment_mode == "production" and not webhook_secret_production:
            raise SettingsError(
                "MERCADOPAGO_WEBHOOK_SECRET_PRODUCTION ausente com PAYMENT_MODE=production "
                "e WEBHOOK_ENABLED=true — o endpoint de webhook aceitaria notificacoes sem "
                "verificar assinatura. Configure o secret antes de subir em producao."
            )

        return cls(
            discord_token=discord_token,
            database_url=database_url,
            environment=environment,
            log_level=log_level,
            discord_application_id=_optional_int("DISCORD_APPLICATION_ID"),
            test_guild_id=_optional_int("TEST_GUILD_ID"),
            db_pool_size=_optional_int("DB_POOL_SIZE") or 10,
            db_max_overflow=_optional_int("DB_MAX_OVERFLOW") or 20,
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
            discord_oauth_client_id=_require("DISCORD_OAUTH_CLIENT_ID"),
            discord_oauth_client_secret=_require("DISCORD_OAUTH_CLIENT_SECRET"),
            discord_oauth_redirect_uri=discord_oauth_redirect_uri,
            jwt_secret_key=jwt_secret_key,
            jwt_access_ttl_seconds=_optional_int("JWT_ACCESS_TTL_SECONDS") or 900,
            refresh_token_ttl_days=_optional_int("REFRESH_TOKEN_TTL_DAYS") or 30,
            storage_provider=(_optional("STORAGE_PROVIDER") or "r2").lower(),
            storage_bucket=_optional("STORAGE_BUCKET"),
            storage_endpoint_url=_optional("STORAGE_ENDPOINT_URL"),
            storage_region=_optional("STORAGE_REGION") or "auto",
            storage_access_key_id=_optional("STORAGE_ACCESS_KEY_ID"),
            storage_secret_access_key=_optional("STORAGE_SECRET_ACCESS_KEY"),
            storage_download_ttl_seconds=_optional_int("STORAGE_DOWNLOAD_TTL_SECONDS") or 600,
            internal_api_secret=internal_api_secret,
            cors_allowed_origins=cors_allowed_origins,
            reconcile_max_concurrency=_optional_int("RECONCILE_MAX_CONCURRENCY") or 5,
            reconcile_guild_timeout_seconds=_optional_int("RECONCILE_GUILD_TIMEOUT_SECONDS") or 30,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.load()
