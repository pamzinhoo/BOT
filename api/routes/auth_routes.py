from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from api.dependencies import get_client_ip, get_current_player
from api.schemas.auth import (
    DeviceCodeRequest,
    DeviceCodeResponse,
    DeviceTokenRequest,
    DeviceTokenResponse,
    LogoutAllResponse,
    LogoutRequest,
    PlayerResponse,
    RefreshRequest,
    TokenResponse,
)
from core.logger import get_logger
from core.rate_limiter import RateLimitExceeded
from services.auth_service import AuthError

if TYPE_CHECKING:
    from database.models.player import Player
    from services.auth_service import AuthService

logger = get_logger("auth_routes")

router = APIRouter(prefix="/auth", tags=["auth"])

_ERROR_STATUS: dict[str, int] = {
    "invalid_user_code": status.HTTP_404_NOT_FOUND,
    "invalid_state": status.HTTP_400_BAD_REQUEST,
    "discord_exchange_failed": status.HTTP_502_BAD_GATEWAY,
    "discord_token_exchange_failed": status.HTTP_502_BAD_GATEWAY,
    "discord_user_fetch_failed": status.HTTP_502_BAD_GATEWAY,
    "device_revoked": status.HTTP_403_FORBIDDEN,
    "invalid_refresh_token": status.HTTP_401_UNAUTHORIZED,
    "session_hijack_suspected": status.HTTP_401_UNAUTHORIZED,
    "refresh_token_expired": status.HTTP_401_UNAUTHORIZED,
    "player_banned": status.HTTP_403_FORBIDDEN,
    "invalid_token": status.HTTP_401_UNAUTHORIZED,
}


def _raise_from_auth_error(exc: AuthError) -> None:
    raise HTTPException(
        status_code=_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST),
        detail={"error": exc.code, "message": str(exc)},
    ) from exc


async def _enforce_rate_limit(auth_service: AuthService, bucket: str, key: str) -> None:
    try:
        await auth_service.enforce_rate_limit(bucket, key)
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": "rate_limited", "message": str(exc)},
            headers={"Retry-After": str(int(exc.retry_after_seconds) + 1)},
        ) from exc


@router.post("/device/code", response_model=DeviceCodeResponse)
async def device_code(request: Request, body: DeviceCodeRequest) -> DeviceCodeResponse:
    auth_service: AuthService = request.app.state.auth_service
    ip = get_client_ip(request)
    await _enforce_rate_limit(auth_service, "device_code", ip or "unknown")

    issued = await auth_service.create_device_login(
        device_uuid=body.device_uuid, os_info=body.os_info, launcher_version=body.launcher_version
    )
    return DeviceCodeResponse(
        device_code=issued.device_code,
        user_code=issued.user_code,
        verification_uri=issued.verification_uri,
        expires_in=issued.expires_in,
        interval=issued.interval,
    )


@router.get("/device/authorize")
async def device_authorize(request: Request, user_code: str) -> RedirectResponse:
    auth_service: AuthService = request.app.state.auth_service
    try:
        discord_url = await auth_service.build_discord_authorize_url(user_code=user_code)
    except AuthError as exc:
        return HTMLResponse(f"<h1>Codigo invalido ou expirado</h1><p>{exc}</p>", status_code=404)
    return RedirectResponse(discord_url)


@router.get("/discord/callback")
async def discord_callback(request: Request, code: str, state: str) -> HTMLResponse:
    auth_service: AuthService = request.app.state.auth_service
    ip = get_client_ip(request)
    await _enforce_rate_limit(auth_service, "callback", ip or "unknown")

    try:
        await auth_service.handle_discord_callback(code=code, state=state, ip=ip)
    except AuthError as exc:
        return HTMLResponse(f"<h1>Nao foi possivel completar o login</h1><p>{exc}</p>", status_code=400)
    return HTMLResponse("<h1>Login concluido</h1><p>Pode fechar esta aba e voltar pro Launcher.</p>")


@router.post("/device/token", response_model=DeviceTokenResponse)
async def device_token(request: Request, body: DeviceTokenRequest) -> DeviceTokenResponse:
    auth_service: AuthService = request.app.state.auth_service
    await _enforce_rate_limit(auth_service, "poll", body.device_code)

    result = await auth_service.poll_device_token(device_code=body.device_code)
    if result.status == "success" and result.tokens is not None:
        return DeviceTokenResponse(
            status=result.status,
            access_token=result.tokens.access_token,
            refresh_token=result.tokens.refresh_token,
            token_type=result.tokens.token_type,
            expires_in=result.tokens.expires_in,
        )
    return DeviceTokenResponse(status=result.status, interval=result.interval)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, body: RefreshRequest) -> TokenResponse:
    auth_service: AuthService = request.app.state.auth_service
    ip = get_client_ip(request)
    await _enforce_rate_limit(auth_service, "refresh", f"{ip}:{body.device_uuid}")

    try:
        tokens = await auth_service.refresh(refresh_token=body.refresh_token, device_uuid=body.device_uuid, ip=ip)
    except AuthError as exc:
        _raise_from_auth_error(exc)
        raise  # pragma: no cover - _raise_from_auth_error sempre levanta
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
        expires_in=tokens.expires_in,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, body: LogoutRequest) -> None:
    auth_service: AuthService = request.app.state.auth_service
    ip = get_client_ip(request)
    await _enforce_rate_limit(auth_service, "logout", ip or "unknown")
    await auth_service.logout(refresh_token=body.refresh_token, ip=ip)


@router.post("/logout/all", response_model=LogoutAllResponse)
async def logout_all(
    request: Request, player: Player = Depends(get_current_player)
) -> LogoutAllResponse:
    auth_service: AuthService = request.app.state.auth_service
    ip = get_client_ip(request)
    await _enforce_rate_limit(auth_service, "logout", ip or "unknown")
    revoked = await auth_service.logout_all(player_id=player.id, ip=ip)
    return LogoutAllResponse(sessions_revoked=revoked)


@router.get("/me", response_model=PlayerResponse)
async def me(player: Player = Depends(get_current_player)) -> PlayerResponse:
    return PlayerResponse(
        id=player.id,
        discord_id=player.discord_id,
        discord_username=player.discord_username,
        linked_at=player.linked_at.isoformat(),
        last_login_at=player.last_login_at.isoformat() if player.last_login_at else None,
    )
