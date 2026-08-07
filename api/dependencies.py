from __future__ import annotations

import hashlib
import hmac
import time
from typing import TYPE_CHECKING

from fastapi import Header, HTTPException, Request, status

from core.rate_limiter import RateLimiter, RateLimitExceeded
from services.auth_service import AuthError

if TYPE_CHECKING:
    from database.models.player import Player
    from services.auth_service import AuthService

# Janela de tolerancia do X-Internal-Timestamp — sem isso uma requisicao
# assinada capturada (log, proxy, MITM parcial) fica reenviavel pra sempre
# com a mesma assinatura valida (replay attack). Mesmo raciocinio aplicado
# ao `ts` do webhook Mercado Pago (providers/mercadopago.py).
_INTERNAL_SIGNATURE_MAX_AGE_SECONDS = 300


def get_client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def enforce_rate_limit(limiter: RateLimiter, key: str) -> None:
    """Mesmo padrao de `AuthService.enforce_rate_limit`, reaproveitado pelas
    rotas de Launcher/download/webhook/internal — todo endpoint publico ou
    autenticado desta API tem que ter algum limite, senao vira superficie de
    DoS/abuso de custo (gerar URL assinada, consultar License, etc)."""
    try:
        await limiter.hit(key)
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": "rate_limited", "message": str(exc)},
            headers={"Retry-After": str(int(exc.retry_after_seconds) + 1)},
        ) from exc


async def verify_internal_signature(
    request: Request,
    x_internal_signature: str | None = Header(default=None),
    x_internal_timestamp: str | None = Header(default=None),
) -> None:
    """Autentica o canal interno Backend<->Bot (`/internal/*`) por HMAC-SHA256
    sobre `timestamp.corpo_cru`, mesmo esquema-base ja usado pra validar
    webhook do Mercado Pago (`providers/mercadopago.py`) — reaproveitado em
    vez de um segundo mecanismo, com o `ts` amarrado na assinatura (nao so
    checado a parte) pra impedir que alguem reaproveite um timestamp fresco
    com um corpo antigo. Headers: `X-Internal-Timestamp: <unix epoch seconds>`,
    `X-Internal-Signature: <hex hmac-sha256(secret, f"{ts}.{corpo}")>`."""
    secret = request.app.state.bot.settings.internal_api_secret
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "internal_api_not_configured",
                "message": "INTERNAL_API_SECRET nao configurado neste backend.",
            },
        )
    if not x_internal_signature or not x_internal_timestamp:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "missing_signature",
                "message": "Headers X-Internal-Signature e X-Internal-Timestamp obrigatorios.",
            },
        )
    try:
        request_ts = int(x_internal_timestamp)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_timestamp", "message": "X-Internal-Timestamp invalido."},
        ) from None
    age = abs(time.time() - request_ts)
    if age > _INTERNAL_SIGNATURE_MAX_AGE_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "stale_timestamp", "message": "X-Internal-Timestamp fora da janela permitida."},
        )

    raw_body = await request.body()
    manifest = f"{x_internal_timestamp}.".encode() + raw_body
    expected = hmac.new(secret.encode(), manifest, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, x_internal_signature.strip().lower()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_signature", "message": "Assinatura HMAC invalida."},
        )


async def get_current_player(
    request: Request, authorization: str | None = Header(default=None)
) -> Player:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "missing_token", "message": "Header Authorization: Bearer <token> obrigatorio."},
        )
    token = authorization.split(" ", 1)[1].strip()
    auth_service: AuthService = request.app.state.auth_service
    try:
        return await auth_service.get_player_from_access_token(token)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail={"error": exc.code, "message": str(exc)}
        ) from exc
