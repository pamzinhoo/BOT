from __future__ import annotations

import uuid

import pytest

from core.security import jwt_service

_SECRET = "a" * 40


def test_encode_decode_roundtrip() -> None:
    player_id, device_id, session_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    token = jwt_service.encode_access_token(
        player_id=player_id,
        device_id=device_id,
        session_id=session_id,
        secret_key=_SECRET,
        ttl_seconds=900,
    )
    claims = jwt_service.decode_access_token(token, secret_key=_SECRET)

    assert claims.player_id == player_id
    assert claims.device_id == device_id
    assert claims.session_id == session_id
    assert claims.key_id == "v1"
    assert claims.jti


def test_decode_rejects_wrong_secret() -> None:
    token = jwt_service.encode_access_token(
        player_id=uuid.uuid4(),
        device_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        secret_key=_SECRET,
        ttl_seconds=900,
    )
    with pytest.raises(jwt_service.JWTError):
        jwt_service.decode_access_token(token, secret_key="not-the-right-secret")


def test_decode_rejects_expired_token() -> None:
    token = jwt_service.encode_access_token(
        player_id=uuid.uuid4(),
        device_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        secret_key=_SECRET,
        ttl_seconds=-1,
    )
    with pytest.raises(jwt_service.JWTError):
        jwt_service.decode_access_token(token, secret_key=_SECRET)


def test_decode_rejects_garbage_token() -> None:
    with pytest.raises(jwt_service.JWTError):
        jwt_service.decode_access_token("not.a.jwt", secret_key=_SECRET)


def test_two_tokens_for_same_session_have_different_jti() -> None:
    player_id, device_id, session_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    kwargs = dict(player_id=player_id, device_id=device_id, session_id=session_id, secret_key=_SECRET, ttl_seconds=900)
    token_a = jwt_service.encode_access_token(**kwargs)
    token_b = jwt_service.encode_access_token(**kwargs)

    claims_a = jwt_service.decode_access_token(token_a, secret_key=_SECRET)
    claims_b = jwt_service.decode_access_token(token_b, secret_key=_SECRET)
    assert claims_a.jti != claims_b.jti
