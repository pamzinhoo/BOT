from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI

from api.routes.internal_routes import router as internal_router
from services.reconciliation_service import GuildReconciliationResult, ReconciliationReport

_SECRET = "test-internal-secret"


def _sign(body: bytes, *, ts: str | None = None) -> tuple[dict[str, str], str]:
    ts = ts if ts is not None else str(int(time.time()))
    manifest = f"{ts}.".encode() + body
    signature = hmac.new(_SECRET.encode(), manifest, hashlib.sha256).hexdigest()
    return {"X-Internal-Timestamp": ts, "X-Internal-Signature": signature}, ts


@pytest.fixture
def bot() -> MagicMock:
    fake_bot = MagicMock()
    fake_bot.settings.internal_api_secret = _SECRET
    fake_bot.role_sync_service.handle_license_event = AsyncMock()
    fake_bot.reconciliation_service.reconcile_all_guilds = AsyncMock(
        return_value=ReconciliationReport(
            guilds_checked=1, roles_granted=2, roles_removed=1, errors=0,
            per_guild=[GuildReconciliationResult(guild_id=1, roles_granted=2, roles_removed=1, errors=0)],
        )
    )
    return fake_bot


@pytest.fixture
def client(bot: MagicMock):
    app = FastAPI()
    app.state.bot = bot
    app.include_router(internal_router)
    transport = httpx.ASGITransport(app=app)
    http_client = httpx.AsyncClient(transport=transport, base_url="http://test")
    http_client.app = app  # type: ignore[attr-defined]
    return http_client


def _license_event_body() -> bytes:
    import json

    return json.dumps(
        {
            "license_id": str(uuid.uuid4()),
            "player_id": str(uuid.uuid4()),
            "product_id": str(uuid.uuid4()),
            "status": "active",
            "event_type": "LICENSE_CREATED",
            "occurred_at": datetime.now(UTC).isoformat(),
        }
    ).encode()


_JSON_CONTENT_TYPE = {"Content-Type": "application/json"}


async def test_license_event_requires_signature_header(client: httpx.AsyncClient) -> None:
    async with client as c:
        r = await c.post("/internal/license-events", content=_license_event_body(), headers=_JSON_CONTENT_TYPE)
        assert r.status_code == 401
        assert r.json()["detail"]["error"] == "missing_signature"


async def test_license_event_requires_timestamp_header(client: httpx.AsyncClient) -> None:
    body = _license_event_body()
    headers, _ts = _sign(body)
    del headers["X-Internal-Timestamp"]
    async with client as c:
        r = await c.post(
            "/internal/license-events", content=body, headers={**_JSON_CONTENT_TYPE, **headers}
        )
        assert r.status_code == 401
        assert r.json()["detail"]["error"] == "missing_signature"


async def test_license_event_rejects_wrong_signature(client: httpx.AsyncClient) -> None:
    body = _license_event_body()
    headers, _ts = _sign(body)
    headers["X-Internal-Signature"] = "0" * 64
    async with client as c:
        r = await c.post(
            "/internal/license-events", content=body, headers={**_JSON_CONTENT_TYPE, **headers}
        )
        assert r.status_code == 401
        assert r.json()["detail"]["error"] == "invalid_signature"


async def test_license_event_rejects_non_numeric_timestamp(client: httpx.AsyncClient) -> None:
    body = _license_event_body()
    headers, _ts = _sign(body)
    headers["X-Internal-Timestamp"] = "not-a-number"
    async with client as c:
        r = await c.post(
            "/internal/license-events", content=body, headers={**_JSON_CONTENT_TYPE, **headers}
        )
        assert r.status_code == 401
        assert r.json()["detail"]["error"] == "invalid_timestamp"


async def test_license_event_rejects_stale_timestamp_as_replay(client: httpx.AsyncClient) -> None:
    body = _license_event_body()
    old_ts = str(int(time.time()) - 3600)
    headers, _ts = _sign(body, ts=old_ts)
    async with client as c:
        r = await c.post(
            "/internal/license-events", content=body, headers={**_JSON_CONTENT_TYPE, **headers}
        )
        assert r.status_code == 401
        assert r.json()["detail"]["error"] == "stale_timestamp"


async def test_license_event_rejects_replay_of_captured_request(client: httpx.AsyncClient, bot: MagicMock) -> None:
    """Assinatura valida e fresca no momento X — reenviada identica no
    momento X+1 dentro da janela ainda passaria (limitacao aceita de um
    esquema HMAC+ts sem nonce, documentada em BACKEND_BOT_INTEGRATION.md);
    o que este teste garante e que a janela de tolerancia e finita e
    aplicada, nao que exista protecao contra replay imediato."""
    body = _license_event_body()
    headers, _ts = _sign(body)
    async with client as c:
        first = await c.post(
            "/internal/license-events", content=body, headers={**_JSON_CONTENT_TYPE, **headers}
        )
        assert first.status_code == 204
        # replay imediato (dentro da janela) — dispatcha de novo, mas o
        # handler do outro lado (RoleSyncService.handle_license_event) e
        # idempotente, entao o replay nao causa efeito colateral duplicado
        second = await c.post(
            "/internal/license-events", content=body, headers={**_JSON_CONTENT_TYPE, **headers}
        )
        assert second.status_code == 204
    assert bot.role_sync_service.handle_license_event.await_count == 2


async def test_license_event_accepts_valid_signature_and_dispatches(
    client: httpx.AsyncClient, bot: MagicMock
) -> None:
    body = _license_event_body()
    headers, _ts = _sign(body)
    async with client as c:
        r = await c.post(
            "/internal/license-events", content=body, headers={**_JSON_CONTENT_TYPE, **headers}
        )
        assert r.status_code == 204
    bot.role_sync_service.handle_license_event.assert_awaited_once()


async def test_reconcile_requires_signature(client: httpx.AsyncClient) -> None:
    async with client as c:
        r = await c.post("/internal/reconcile", content=b"")
        assert r.status_code == 401


async def test_reconcile_returns_report_with_valid_signature(client: httpx.AsyncClient, bot: MagicMock) -> None:
    body = b""
    headers, _ts = _sign(body)
    async with client as c:
        r = await c.post("/internal/reconcile", content=body, headers=headers)
        assert r.status_code == 200
        payload = r.json()
        assert payload["guilds_checked"] == 1
        assert payload["roles_granted"] == 2
        assert payload["per_guild"][0]["guild_id"] == 1
    bot.reconciliation_service.reconcile_all_guilds.assert_awaited_once()


async def test_internal_routes_return_503_when_secret_not_configured(bot: MagicMock) -> None:
    bot.settings.internal_api_secret = None
    app = FastAPI()
    app.state.bot = bot
    app.include_router(internal_router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/internal/reconcile", content=b"", headers={"X-Internal-Signature": "x", "X-Internal-Timestamp": "1"}
        )
        assert r.status_code == 503
        assert r.json()["detail"]["error"] == "internal_api_not_configured"


async def test_signature_is_case_insensitive_hex(client: httpx.AsyncClient) -> None:
    body = b""
    headers, _ts = _sign(body)
    headers["X-Internal-Signature"] = headers["X-Internal-Signature"].upper()
    async with client as c:
        r = await c.post("/internal/reconcile", content=body, headers=headers)
        assert r.status_code == 200


async def test_signature_bound_to_timestamp_cannot_be_recombined(client: httpx.AsyncClient) -> None:
    """Assinatura calculada pra ts=A nao pode ser reaproveitada com ts=B
    (mesmo corpo) — o `ts` faz parte do manifest assinado, nao e so checado
    a parte."""
    body = b""
    headers, ts = _sign(body)
    headers["X-Internal-Timestamp"] = str(int(ts) + 1)  # ainda fresco, mas nao foi o ts assinado
    async with client as c:
        r = await c.post("/internal/reconcile", content=body, headers=headers)
        assert r.status_code == 401
        assert r.json()["detail"]["error"] == "invalid_signature"
