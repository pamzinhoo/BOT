from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import discord
import httpx
import pytest
from fastapi import FastAPI

from api.dependencies import get_current_player
from api.routes.player_routes import router as player_router
from database.models.payment import PaymentStatus
from database.models.player import Player
from providers.base import ChargeResult
from services.dlc_service import DlcService
from services.license_service import LicenseService
from tests._fakes_dlc import DlcFakeStore, install_dlc_fakes
from tests._fakes_dlc import FakeDatabase as DlcFakeDatabase
from tests._fakes_license import FakeDatabase as LicenseFakeDatabase
from tests._fakes_license import LicenseFakeStore
from tests._fakes_license import install_fake_repositories as install_license_fakes


def _player() -> Player:
    player = Player(discord_id=42, discord_username="tester", linked_at=datetime.now(UTC))
    player.id = uuid.uuid4()
    return player


@pytest.fixture
def player() -> Player:
    return _player()


@pytest.fixture
def stores(monkeypatch):
    dlc_store = DlcFakeStore()
    license_store = LicenseFakeStore()
    install_dlc_fakes(monkeypatch, dlc_store)
    install_license_fakes(monkeypatch, license_store)
    return dlc_store, license_store


@pytest.fixture
def client(stores, player: Player):
    dlc_store, license_store = stores
    license_service = LicenseService(LicenseFakeDatabase(license_store))
    dlc_service = DlcService(DlcFakeDatabase(dlc_store), license_service, bot=None)

    app = FastAPI()
    app.state.license_service = license_service
    app.state.dlc_service = dlc_service
    app.include_router(player_router)
    app.dependency_overrides[get_current_player] = lambda: player

    transport = httpx.ASGITransport(app=app)
    http_client = httpx.AsyncClient(transport=transport, base_url="http://test")
    http_client.dlc_service = dlc_service  # type: ignore[attr-defined]
    http_client.license_service = license_service  # type: ignore[attr-defined]
    return http_client


async def test_dlcs_catalog_reflects_ownership(client: httpx.AsyncClient, player: Player) -> None:
    free = await client.dlc_service.create_free(
        guild_id=1, name="Empress", slug="empress", description=None, required_role_id=10
    )
    paid, _plan = await client.dlc_service.create_paid(
        guild_id=1, name="Devil", slug="devil", description=None, price_amount=1490, role_id=20
    )
    await client.license_service.grant_or_renew(player.id, free.id, purchase_source="role_grant")

    async with client as c:
        r = await c.get("/player/dlcs")
        assert r.status_code == 200
        body = {item["slug"]: item for item in r.json()}
        assert body["empress"]["unlocked"] is True
        assert body["empress"]["access_type"] == "free"
        assert body["devil"]["unlocked"] is False
        assert body["devil"]["access_type"] == "paid"
        assert body["devil"]["price_amount"] == 1490


async def test_dlcs_catalog_hides_inactive(client: httpx.AsyncClient) -> None:
    product = await client.dlc_service.create_free(
        guild_id=1, name="Old", slug="old-dlc", description=None, required_role_id=1
    )
    await client.dlc_service.toggle_active(product.id, is_active=False)

    async with client as c:
        r = await c.get("/player/dlcs")
        assert r.status_code == 200
        assert all(item["slug"] != "old-dlc" for item in r.json())


async def test_purchase_dlc_never_trusts_client_price(client: httpx.AsyncClient, monkeypatch) -> None:
    """O corpo do POST nunca carrega preco — o teste garante que o preco
    cobrado vem sempre do Plan lido do banco, reforcando que nao ha campo
    manipulavel na requisicao."""
    product, plan = await client.dlc_service.create_paid(
        guild_id=1, name="Devil", slug="devil-2", description=None, price_amount=1490, role_id=20
    )

    member = MagicMock(spec=discord.Member)
    member.id = 42
    guild = MagicMock(spec=discord.Guild)
    guild.get_member.return_value = member

    bot = MagicMock()
    bot.get_guild.return_value = guild
    captured_amount = {}

    async def fake_start_purchase(_member, called_plan, _cycle, **_kwargs):
        captured_amount["amount"] = called_plan.price_one_time
        payment = MagicMock()
        payment.id = uuid.uuid4()
        result = ChargeResult(
            external_id="ext-1", status=PaymentStatus.PENDING,
            checkout_url=None, qr_code="00020126", qr_code_base64=None,
        )
        return "subscription", payment, result

    bot.subscription_service.start_purchase = AsyncMock(side_effect=fake_start_purchase)
    client.dlc_service._bot = bot

    async with client as c:
        r = await c.post(f"/player/dlcs/{product.id}/purchase", json={})
        assert r.status_code == 200
        body = r.json()
        assert body["qr_code"] == "00020126"

    assert captured_amount["amount"] == 1490


async def test_purchase_free_dlc_rejected(client: httpx.AsyncClient) -> None:
    product = await client.dlc_service.create_free(
        guild_id=1, name="Empress", slug="empress-2", description=None, required_role_id=10
    )
    bot = MagicMock()
    client.dlc_service._bot = bot

    async with client as c:
        r = await c.post(f"/player/dlcs/{product.id}/purchase", json={})
        assert r.status_code == 422
        assert r.json()["detail"]["error"] == "dlc_purchase_error"


async def test_purchase_unknown_dlc_rejected(client: httpx.AsyncClient) -> None:
    bot = MagicMock()
    client.dlc_service._bot = bot

    async with client as c:
        r = await c.post(f"/player/dlcs/{uuid.uuid4()}/purchase", json={})
        assert r.status_code == 422
