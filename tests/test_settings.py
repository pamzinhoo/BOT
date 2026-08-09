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


# --- seguranca (Fase 6) ------------------------------------------------------


def test_load_raises_when_jwt_secret_too_short(valid_env, monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "short-secret")
    with pytest.raises(SettingsError, match="JWT_SECRET_KEY"):
        Settings.load()


def test_load_accepts_jwt_secret_at_minimum_length(valid_env, monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 32)
    settings = Settings.load()
    assert len(settings.jwt_secret_key) == 32


def test_load_raises_when_internal_api_secret_too_short(valid_env, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SECRET", "too-short")
    with pytest.raises(SettingsError, match="INTERNAL_API_SECRET"):
        Settings.load()


def test_load_accepts_internal_api_secret_at_minimum_length(valid_env, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SECRET", "y" * 32)
    settings = Settings.load()
    assert settings.internal_api_secret == "y" * 32


def test_internal_api_secret_optional_by_default(valid_env):
    settings = Settings.load()
    assert settings.internal_api_secret is None
    assert settings.internal_api_configured is False


def test_load_raises_when_production_public_base_url_not_https(valid_env, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://example.com")
    with pytest.raises(SettingsError, match="HTTPS"):
        Settings.load()


def test_load_accepts_production_with_https_public_base_url(valid_env, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.com")
    settings = Settings.load()
    assert settings.public_base_url == "https://example.com"


def test_development_allows_http_public_base_url(valid_env, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://localhost:8000")
    settings = Settings.load()
    assert settings.public_base_url == "http://localhost:8000"


def test_cors_allowed_origins_defaults_to_empty(valid_env):
    settings = Settings.load()
    assert settings.cors_allowed_origins == ()


def test_cors_allowed_origins_parses_comma_separated_list(valid_env, monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://a.example.com, https://b.example.com")
    settings = Settings.load()
    assert settings.cors_allowed_origins == ("https://a.example.com", "https://b.example.com")
