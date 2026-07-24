from __future__ import annotations

import pytest

from config.settings import Settings, SettingsError


def test_load_raises_when_discord_token_missing(clean_env, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    with pytest.raises(SettingsError, match="DISCORD_TOKEN"):
        Settings.load()


def test_load_raises_when_database_url_missing(clean_env, monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "fake-token")
    with pytest.raises(SettingsError, match="DATABASE_URL"):
        Settings.load()


def test_load_raises_when_database_url_not_asyncpg(clean_env, monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "fake-token")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    with pytest.raises(SettingsError, match="asyncpg"):
        Settings.load()


def test_load_raises_on_invalid_environment(clean_env, monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "fake-token")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("ENVIRONMENT", "staging")
    with pytest.raises(SettingsError, match="ENVIRONMENT"):
        Settings.load()


def test_load_raises_on_invalid_log_level(clean_env, monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "fake-token")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("LOG_LEVEL", "VERBOSE")
    with pytest.raises(SettingsError, match="LOG_LEVEL"):
        Settings.load()


def test_load_succeeds_with_valid_env(valid_env):
    settings = Settings.load()
    assert settings.discord_token == "fake-token-for-tests"
    assert settings.environment == "development"
    assert settings.log_level == "DEBUG"
    assert settings.is_production is False
    assert settings.discord_application_id is None


def test_discord_application_id_parsed_as_int(valid_env, monkeypatch):
    monkeypatch.setenv("DISCORD_APPLICATION_ID", "123456789")
    settings = Settings.load()
    assert settings.discord_application_id == 123456789


def test_discord_application_id_invalid_raises(valid_env, monkeypatch):
    monkeypatch.setenv("DISCORD_APPLICATION_ID", "not-an-int")
    with pytest.raises(SettingsError, match="DISCORD_APPLICATION_ID"):
        Settings.load()


def test_get_settings_is_cached(valid_env):
    from config.settings import get_settings

    first = get_settings()
    second = get_settings()
    assert first is second
