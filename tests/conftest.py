from __future__ import annotations

from collections.abc import Iterator

import pytest

_ENV_KEYS = (
    "DISCORD_TOKEN",
    "DISCORD_APPLICATION_ID",
    "ENVIRONMENT",
    "DATABASE_URL",
    "LOG_LEVEL",
    "DISCORD_OAUTH_CLIENT_ID",
    "DISCORD_OAUTH_CLIENT_SECRET",
    "DISCORD_OAUTH_REDIRECT_URI",
    "JWT_SECRET_KEY",
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield


@pytest.fixture
def valid_env(monkeypatch: pytest.MonkeyPatch, clean_env: None) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "fake-token-for-tests")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/bot_limerence"
    )
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("DISCORD_OAUTH_CLIENT_ID", "fake-client-id")
    monkeypatch.setenv("DISCORD_OAUTH_CLIENT_SECRET", "fake-client-secret")
    monkeypatch.setenv("JWT_SECRET_KEY", "fake-jwt-secret-for-tests-min-32-bytes-long")


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    from config.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
