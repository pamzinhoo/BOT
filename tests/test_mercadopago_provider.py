from __future__ import annotations

import hashlib
import hmac
import time

import pytest

from providers.mercadopago import MercadoPagoProvider

_SECRET = "webhook-secret"


def _sign(*, data_id: str, request_id: str, ts: str) -> str:
    manifest = f"id:{data_id};request-id:{request_id};ts:{ts};"
    v1 = hmac.new(_SECRET.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return f"ts={ts},v1={v1}"


def _headers(*, data_id: str = "123", request_id: str = "req-1", ts: str | None = None) -> dict[str, str]:
    ts = ts if ts is not None else str(int(time.time()))
    return {
        "x-signature": _sign(data_id=data_id, request_id=request_id, ts=ts),
        "x-request-id": request_id,
        "x-data-id": data_id,
    }


@pytest.fixture
def provider() -> MercadoPagoProvider:
    return MercadoPagoProvider(access_token="fake-token", webhook_secret=_SECRET)


async def test_valid_fresh_signature_is_accepted(provider: MercadoPagoProvider) -> None:
    assert await provider.validate_webhook(_headers(), b"", _SECRET) is True


async def test_missing_secret_is_rejected(provider: MercadoPagoProvider) -> None:
    assert await provider.validate_webhook(_headers(), b"", None) is False


async def test_missing_headers_is_rejected(provider: MercadoPagoProvider) -> None:
    assert await provider.validate_webhook({}, b"", _SECRET) is False


async def test_wrong_signature_is_rejected(provider: MercadoPagoProvider) -> None:
    headers = _headers()
    headers["x-signature"] = headers["x-signature"].replace("v1=", "v1=deadbeef")
    assert await provider.validate_webhook(headers, b"", _SECRET) is False


async def test_tampered_data_id_is_rejected(provider: MercadoPagoProvider) -> None:
    """Assinatura calculada pra data_id=123, mas o header x-data-id foi
    trocado pra outro pagamento — manifest nao bate mais."""
    headers = _headers(data_id="123")
    headers["x-data-id"] = "999"
    assert await provider.validate_webhook(headers, b"", _SECRET) is False


async def test_stale_timestamp_is_rejected_as_replay(provider: MercadoPagoProvider) -> None:
    old_ts = str(int(time.time()) - 3600)  # 1h atras — bem alem da janela de 300s
    assert await provider.validate_webhook(_headers(ts=old_ts), b"", _SECRET) is False


async def test_timestamp_in_milliseconds_is_handled(provider: MercadoPagoProvider) -> None:
    ts_ms = str(int(time.time() * 1000))
    assert await provider.validate_webhook(_headers(ts=ts_ms), b"", _SECRET) is True


async def test_non_numeric_timestamp_is_rejected(provider: MercadoPagoProvider) -> None:
    data_id, request_id = "123", "req-1"
    manifest = f"id:{data_id};request-id:{request_id};ts:not-a-number;"
    v1 = hmac.new(_SECRET.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    headers = {
        "x-signature": f"ts=not-a-number,v1={v1}",
        "x-request-id": request_id,
        "x-data-id": data_id,
    }
    assert await provider.validate_webhook(headers, b"", _SECRET) is False
