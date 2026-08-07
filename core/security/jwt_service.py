from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

_ALGORITHM = "HS256"
_CURRENT_KEY_ID = "v1"


class JWTError(Exception):
    """Token ausente, expirado ou com assinatura invalida."""


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    player_id: uuid.UUID
    device_id: uuid.UUID
    session_id: uuid.UUID
    jti: str
    key_id: str
    expires_at: datetime


def encode_access_token(
    *,
    player_id: uuid.UUID,
    device_id: uuid.UUID,
    session_id: uuid.UUID,
    secret_key: str,
    ttl_seconds: int,
    key_id: str = _CURRENT_KEY_ID,
) -> str:
    """Emite o access token curto que o Launcher usa pra chamar o resto da
    API. `sid` (session_id) referencia a LauncherSession — nao e usado pra
    revogar em tempo real (o token e stateless, curto de proposito), mas
    fica disponivel pra auditoria/correlacao. `kid` no header deixa o
    esquema pronto pra rotacao de chave sem quebrar tokens ja emitidos."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(player_id),
        "device_id": str(device_id),
        "sid": str(session_id),
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
    }
    return jwt.encode(payload, secret_key, algorithm=_ALGORITHM, headers={"kid": key_id})


def decode_access_token(token: str, *, secret_key: str) -> AccessTokenClaims:
    try:
        header = jwt.get_unverified_header(token)
        payload = jwt.decode(token, secret_key, algorithms=[_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise JWTError(str(exc)) from exc

    try:
        return AccessTokenClaims(
            player_id=uuid.UUID(payload["sub"]),
            device_id=uuid.UUID(payload["device_id"]),
            session_id=uuid.UUID(payload["sid"]),
            jti=payload["jti"],
            key_id=header.get("kid", _CURRENT_KEY_ID),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
        )
    except (KeyError, ValueError) as exc:
        raise JWTError(f"Claim ausente ou invalida no token: {exc}") from exc
