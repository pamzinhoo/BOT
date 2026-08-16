"""Ciclo de vida da aiohttp.ClientSession compartilhada do MercadoPagoProvider
(Fase 2 — reuso de connection pool HTTP, providers/mercadopago.py). Cobre: nao
criacao no import, criacao lazy dentro do loop rodando, reuso entre chamadas e
entre instancias de MercadoPagoProvider, protecao contra corrida na criacao,
fechamento idempotente, recriacao apos fechamento e integracao com
Bot.close(). Nenhuma chamada real ao Mercado Pago — aiohttp.ClientSession.request
e mockado."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

import providers.mercadopago as mp
from config.settings import Settings
from core.bot import LimerenceBot
from database.database import Database
from providers.mercadopago import MercadoPagoProvider


@pytest.fixture(autouse=True)
async def _reset_shared_session() -> AsyncIterator[None]:
    """Isola cada teste do estado global do modulo — sem isso, uma sessao
    criada por um teste vazaria pro proximo (mesmo processo, mesmo loop de
    evento por teste com pytest-asyncio no modo function). Fixture async pra
    poder fechar a sessao dentro do MESMO loop em que ela foi criada — cada
    teste roda em loop proprio, e ClientSession.close() de outro loop
    estoura RuntimeError."""
    mp._shared_session = None
    yield
    if mp._shared_session is not None and not mp._shared_session.closed:
        await mp._shared_session.close()
    mp._shared_session = None


def _fake_response(*, status: int = 200, payload: dict[str, object] | None = None):
    @asynccontextmanager
    async def _request(*args: object, **kwargs: object):
        response = AsyncMock()
        response.status = status
        response.json = AsyncMock(return_value=payload or {"id": "123", "status": "approved"})
        yield response

    return _request


# --- criacao / import -------------------------------------------------------


def test_importing_module_does_not_create_client_session() -> None:
    """Reimportar o modulo num processo limpo nao deve instanciar
    ClientSession fora de um loop rodando (import roda em modulo-level, sem
    loop ativo — criar la quebraria em runtime real)."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import providers.mercadopago as mp; "
            "assert mp._shared_session is None, 'ClientSession criada no import'; "
            "print('OK')",
        ],
        cwd=str(__import__("pathlib").Path(__file__).resolve().parent.parent),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


async def test_no_session_before_first_request() -> None:
    assert mp._shared_session is None


async def test_first_request_creates_session() -> None:
    provider = MercadoPagoProvider(access_token="fake-token", webhook_secret=None)
    assert mp._shared_session is None
    with patch.object(aiohttp.ClientSession, "request", _fake_response()):
        await provider.get_payment("123")
    assert mp._shared_session is not None
    assert not mp._shared_session.closed


# --- reuso -------------------------------------------------------------------


async def test_second_request_reuses_same_session() -> None:
    provider = MercadoPagoProvider(access_token="fake-token", webhook_secret=None)
    with patch.object(aiohttp.ClientSession, "request", _fake_response()):
        await provider.get_payment("123")
        first_session = mp._shared_session
        await provider.get_payment("456")
        second_session = mp._shared_session
    assert first_session is second_session


async def test_different_provider_instances_share_the_same_session() -> None:
    """payment_service.resolve_provider / webhook_service instanciam um
    MercadoPagoProvider novo por chamada — a sessao precisa ser reaproveitada
    entre instancias, nao so dentro da mesma instancia."""
    provider_a = MercadoPagoProvider(access_token="token-a", webhook_secret=None)
    provider_b = MercadoPagoProvider(access_token="token-b", webhook_secret=None)
    with patch.object(aiohttp.ClientSession, "request", _fake_response()):
        await provider_a.get_payment("123")
        await provider_b.get_payment("456")
    assert mp._shared_session is not None


async def test_concurrent_requests_create_only_one_session() -> None:
    provider = MercadoPagoProvider(access_token="fake-token", webhook_secret=None)
    created = []
    real_init = aiohttp.ClientSession.__init__

    def _tracking_init(self: aiohttp.ClientSession, *args: object, **kwargs: object) -> None:
        created.append(self)
        real_init(self, *args, **kwargs)

    with (
        patch.object(aiohttp.ClientSession, "request", _fake_response()),
        patch.object(aiohttp.ClientSession, "__init__", _tracking_init),
    ):
        await asyncio.gather(*(provider.get_payment(str(i)) for i in range(20)))

    assert len(created) == 1


# --- fechamento / recriacao ---------------------------------------------------


async def test_close_session_closes_the_session() -> None:
    provider = MercadoPagoProvider(access_token="fake-token", webhook_secret=None)
    with patch.object(aiohttp.ClientSession, "request", _fake_response()):
        await provider.get_payment("123")
    session = mp._shared_session
    assert session is not None
    await mp.close_session()
    assert session.closed
    assert mp._shared_session is None


async def test_close_session_without_prior_session_is_a_noop() -> None:
    assert mp._shared_session is None
    await mp.close_session()  # nao deve levantar
    assert mp._shared_session is None


async def test_close_session_is_idempotent() -> None:
    provider = MercadoPagoProvider(access_token="fake-token", webhook_secret=None)
    with patch.object(aiohttp.ClientSession, "request", _fake_response()):
        await provider.get_payment("123")
    await mp.close_session()
    await mp.close_session()  # segunda chamada nao deve levantar


async def test_new_session_created_after_close() -> None:
    provider = MercadoPagoProvider(access_token="fake-token", webhook_secret=None)
    with patch.object(aiohttp.ClientSession, "request", _fake_response()):
        await provider.get_payment("123")
        old_session = mp._shared_session
        await mp.close_session()
        assert mp._shared_session is None

        await provider.get_payment("456")
        new_session = mp._shared_session

    assert new_session is not None
    assert new_session is not old_session
    assert not new_session.closed


# --- integracao com Bot.close() ----------------------------------------------


async def test_bot_close_closes_the_mercadopago_session() -> None:
    settings = Settings(
        discord_token="fake-token",
        database_url="postgresql+asyncpg://u:p@localhost:5432/db",
        environment="development",
        log_level="DEBUG",
    )
    database = Database(settings.database_url)
    bot = LimerenceBot(settings=settings, database=database)

    provider = MercadoPagoProvider(access_token="fake-token", webhook_secret=None)
    with patch.object(aiohttp.ClientSession, "request", _fake_response()):
        await provider.get_payment("123")
    session = mp._shared_session
    assert session is not None

    await bot.close()

    assert session.closed
    assert mp._shared_session is None
