"""Ciclo de vida da aiohttp.ClientSession compartilhada do AuthService (item 11
da auditoria de performance) — mesmo padrao ja validado em
tests/test_mercadopago_session_lifecycle.py, so trocando o modulo/gatilho:
aqui o gatilho e _exchange_and_fetch_discord_user (troca de code OAuth +
busca de perfil), nao uma chamada ao Mercado Pago."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

import services.auth_service as auth_service_module
from config.settings import Settings
from core.bot import LimerenceBot
from database.database import Database
from services.auth_service import AuthService


@pytest.fixture(autouse=True)
async def _reset_shared_session() -> AsyncIterator[None]:
    auth_service_module._shared_session = None
    yield
    if auth_service_module._shared_session is not None and not auth_service_module._shared_session.closed:
        await auth_service_module._shared_session.close()
    auth_service_module._shared_session = None


def _settings() -> Settings:
    return Settings(
        discord_token="fake-token",
        database_url="postgresql+asyncpg://u:p@localhost:5432/db",
        environment="development",
        log_level="DEBUG",
    )


def _fake_oauth_responses():
    """`AuthService._exchange_and_fetch_discord_user` faz `await
    http.post(...)`/`await http.get(...)` diretamente (nao `async with`) —
    o mock precisa ser awaitable simples, nao um context manager."""
    token_response = AsyncMock()
    token_response.status = 200
    token_response.json = AsyncMock(return_value={"access_token": "discord-token"})

    user_response = AsyncMock()
    user_response.status = 200
    user_response.json = AsyncMock(return_value={"id": "42", "username": "tester"})

    post = AsyncMock(return_value=token_response)
    get = AsyncMock(return_value=user_response)
    return post, get


async def _exchange(service: AuthService) -> None:
    post, get = _fake_oauth_responses()
    with patch.object(aiohttp.ClientSession, "post", post), patch.object(aiohttp.ClientSession, "get", get):
        await service._exchange_and_fetch_discord_user(code="abc", code_verifier="verifier")


def _service() -> AuthService:
    return AuthService(Database(_settings().database_url), _settings())


async def test_importing_module_does_not_create_client_session() -> None:
    assert auth_service_module._shared_session is None


async def test_first_exchange_creates_session() -> None:
    service = _service()
    assert auth_service_module._shared_session is None
    await _exchange(service)
    assert auth_service_module._shared_session is not None
    assert not auth_service_module._shared_session.closed


async def test_second_exchange_reuses_same_session() -> None:
    service = _service()
    await _exchange(service)
    first = auth_service_module._shared_session
    await _exchange(service)
    second = auth_service_module._shared_session
    assert first is second


async def test_close_session_closes_the_session() -> None:
    service = _service()
    await _exchange(service)
    session = auth_service_module._shared_session
    assert session is not None
    await auth_service_module.close_session()
    assert session.closed
    assert auth_service_module._shared_session is None


async def test_close_session_without_prior_session_is_a_noop() -> None:
    assert auth_service_module._shared_session is None
    await auth_service_module.close_session()
    assert auth_service_module._shared_session is None


async def test_close_session_is_idempotent() -> None:
    service = _service()
    await _exchange(service)
    await auth_service_module.close_session()
    await auth_service_module.close_session()  # nao deve levantar


async def test_bot_close_closes_the_auth_session() -> None:
    settings = _settings()
    database = Database(settings.database_url)
    bot = LimerenceBot(settings=settings, database=database)

    service = _service()
    await _exchange(service)
    session = auth_service_module._shared_session
    assert session is not None

    await bot.close()

    assert session.closed
    assert auth_service_module._shared_session is None
