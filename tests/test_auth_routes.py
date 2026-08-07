from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI

from api.routes.auth_routes import router as auth_router
from services.auth_service import AuthService
from tests._fakes_auth import AuthFakeStore, FakeDatabase, install_fake_repositories


@pytest.fixture
def store() -> AuthFakeStore:
    return AuthFakeStore()


@pytest.fixture
def client(monkeypatch, store: AuthFakeStore, valid_env):
    from config.settings import get_settings

    install_fake_repositories(monkeypatch, store)
    app = FastAPI()
    app.state.auth_service = AuthService(FakeDatabase(store), get_settings())
    app.include_router(auth_router)
    transport = httpx.ASGITransport(app=app)
    http_client = httpx.AsyncClient(transport=transport, base_url="http://test")
    http_client.app = app  # type: ignore[attr-defined]
    return http_client


async def test_device_code_then_poll_pending(client: httpx.AsyncClient) -> None:
    async with client as c:
        r = await c.post("/auth/device/code", json={"device_uuid": str(uuid.uuid4()), "os_info": "Windows 11"})
        assert r.status_code == 200
        body = r.json()
        assert body["device_code"]
        assert body["user_code"]

        r2 = await c.post("/auth/device/token", json={"device_code": body["device_code"]})
        assert r2.status_code == 200
        assert r2.json()["status"] == "authorization_pending"


async def test_device_token_unknown_code_is_expired(client: httpx.AsyncClient) -> None:
    async with client as c:
        r = await c.post("/auth/device/token", json={"device_code": "nope"})
        assert r.status_code == 200
        assert r.json()["status"] == "expired_token"


async def test_device_authorize_redirects_to_discord(client: httpx.AsyncClient) -> None:
    async with client as c:
        r = await c.post("/auth/device/code", json={"device_uuid": str(uuid.uuid4())})
        user_code = r.json()["user_code"]

        r2 = await c.get(f"/auth/device/authorize?user_code={user_code}", follow_redirects=False)
        assert r2.status_code == 307
        assert r2.headers["location"].startswith("https://discord.com/oauth2/authorize?")


async def test_device_authorize_invalid_code_returns_404(client: httpx.AsyncClient) -> None:
    async with client as c:
        r = await c.get("/auth/device/authorize?user_code=ZZZZ-ZZZZ", follow_redirects=False)
        assert r.status_code == 404


async def test_refresh_with_bogus_token_is_401(client: httpx.AsyncClient) -> None:
    async with client as c:
        r = await c.post(
            "/auth/refresh", json={"refresh_token": "bogus", "device_uuid": str(uuid.uuid4())}
        )
        assert r.status_code == 401
        assert r.json()["detail"]["error"] == "invalid_refresh_token"


async def test_logout_bogus_token_is_204_idempotent(client: httpx.AsyncClient) -> None:
    async with client as c:
        r = await c.post("/auth/logout", json={"refresh_token": "bogus"})
        assert r.status_code == 204


async def test_me_without_token_is_401(client: httpx.AsyncClient) -> None:
    async with client as c:
        r = await c.get("/auth/me")
        assert r.status_code == 401
        assert r.json()["detail"]["error"] == "missing_token"


async def test_me_with_garbage_token_is_401(client: httpx.AsyncClient) -> None:
    async with client as c:
        r = await c.get("/auth/me", headers={"Authorization": "Bearer garbage"})
        assert r.status_code == 401
        assert r.json()["detail"]["error"] == "invalid_token"


async def test_device_code_rate_limited_after_ten_hits(client: httpx.AsyncClient) -> None:
    async with client as c:
        device_uuid = str(uuid.uuid4())
        for _ in range(10):
            r = await c.post("/auth/device/code", json={"device_uuid": device_uuid})
            assert r.status_code == 200
        r = await c.post("/auth/device/code", json={"device_uuid": device_uuid})
        assert r.status_code == 429
        assert "Retry-After" in r.headers


async def test_full_login_flow_then_refresh_and_logout(
    client: httpx.AsyncClient, store: AuthFakeStore, monkeypatch
) -> None:
    async def fake_exchange(self, *, code, code_verifier):
        return 1234567890, "e2e-player"

    monkeypatch.setattr(AuthService, "_exchange_and_fetch_discord_user", fake_exchange)

    async with client as c:
        r = await c.post("/auth/device/code", json={"device_uuid": str(uuid.uuid4())})
        device_code = r.json()["device_code"]

        auth_service: AuthService = c.app.state.auth_service  # type: ignore[attr-defined]
        pending = auth_service._pending_logins[device_code]

        r2 = await c.get(f"/auth/discord/callback?code=abc&state={pending.state}")
        assert r2.status_code == 200

        r3 = await c.post("/auth/device/token", json={"device_code": device_code})
        assert r3.status_code == 200
        tokens = r3.json()
        assert tokens["status"] == "success"
        assert tokens["access_token"]
        assert tokens["refresh_token"]

        r4 = await c.get("/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
        assert r4.status_code == 200
        assert r4.json()["discord_id"] == 1234567890

        r5 = await c.post(
            "/auth/refresh",
            json={"refresh_token": tokens["refresh_token"], "device_uuid": list(store.devices.values())[0].device_uuid.__str__()},
        )
        assert r5.status_code == 200
        new_tokens = r5.json()
        assert new_tokens["refresh_token"] != tokens["refresh_token"]

        # reuso do refresh token antigo (ja rotacionado) tem que ser rejeitado
        r6 = await c.post(
            "/auth/refresh",
            json={"refresh_token": tokens["refresh_token"], "device_uuid": list(store.devices.values())[0].device_uuid.__str__()},
        )
        assert r6.status_code == 401
        assert r6.json()["detail"]["error"] == "session_hijack_suspected"

        r7 = await c.post("/auth/logout", json={"refresh_token": new_tokens["refresh_token"]})
        assert r7.status_code == 204
