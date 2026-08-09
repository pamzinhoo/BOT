from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request, status

from api.dependencies import enforce_rate_limit, get_client_ip, get_current_player
from api.schemas.launcher import (
    DownloadCompleteRequest,
    DownloadCompleteResponse,
    DownloadRequest,
    DownloadResponse,
    UpdateRequest,
    UpdateResponse,
)
from core.rate_limiter import RateLimiter
from database.models.game_manifest import ManifestEntryType
from database.models.launcher_version import LauncherPlatform
from services.download_service import DownloadError

if TYPE_CHECKING:
    from database.models.player import Player
    from services.download_service import DownloadService

router = APIRouter(tags=["download"])

# Autorizar download gera custo real (URL assinada, linha de auditoria) —
# limite generoso o bastante pra um Launcher legitimo baixando varias DLCs
# em sequencia, apertado o bastante pra travar automacao/scraping de conteudo.
_download_limiter = RateLimiter(max_hits=30, window_seconds=300)
_complete_limiter = RateLimiter(max_hits=60, window_seconds=300)
# /update e publico (sem auth) — limite por IP, mais generoso que device_code
# de auth porque um parque de maquinas atras de NAT compartilha IP.
_update_limiter = RateLimiter(max_hits=30, window_seconds=60)

_ERROR_STATUS: dict[str, int] = {
    "license_required": status.HTTP_403_FORBIDDEN,
    "manifest_not_found": status.HTTP_404_NOT_FOUND,
    "version_not_found": status.HTTP_404_NOT_FOUND,
    "download_not_found": status.HTTP_404_NOT_FOUND,
    "storage_not_configured": status.HTTP_503_SERVICE_UNAVAILABLE,
    "storage_error": status.HTTP_502_BAD_GATEWAY,
}


def _raise_from_download_error(exc: DownloadError) -> None:
    raise HTTPException(
        status_code=_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST),
        detail={"error": exc.code, "message": exc.message},
    ) from exc


def _parse_platform(platform: str) -> LauncherPlatform:
    try:
        return LauncherPlatform(platform.lower())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_platform", "message": f"Plataforma invalida: {platform!r}."},
        ) from None


def _parse_entry_type(entry_type: str) -> ManifestEntryType:
    try:
        return ManifestEntryType(entry_type.lower())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_entry_type", "message": f"Tipo de entrada invalido: {entry_type!r}."},
        ) from None


@router.post("/download", response_model=DownloadResponse)
async def authorize_download(
    request: Request, body: DownloadRequest, player: Player = Depends(get_current_player)
) -> DownloadResponse:
    """Reconfirma License ACTIVE aqui mesmo que /launcher/manifest ja tenha
    sido consultado antes — nunca reaproveita a checagem anterior. Retorna
    URL de download temporaria (nunca permanente), com versao/sha256/size do
    manifest pra o Launcher validar integridade apos o download."""
    download_service: DownloadService = request.app.state.download_service
    entry_type = _parse_entry_type(body.entry_type)
    ip = get_client_ip(request)
    await enforce_rate_limit(_download_limiter, str(player.id))
    try:
        authorization = await download_service.authorize_download(
            player,
            body.product_id,
            entry_type=entry_type,
            device_id=body.device_uuid,
            ip_address=ip,
        )
    except DownloadError as exc:
        _raise_from_download_error(exc)
        raise  # pragma: no cover
    return DownloadResponse(
        download_id=authorization.download_id,
        url=authorization.url,
        version=authorization.version,
        sha256=authorization.sha256,
        size_bytes=authorization.size_bytes,
        entry_type=authorization.entry_type.value,
        expires_at=authorization.expires_at.isoformat(),
    )


@router.post("/download/{download_id}/complete", response_model=DownloadCompleteResponse)
async def complete_download(
    request: Request,
    download_id: uuid.UUID,
    body: DownloadCompleteRequest,
    player: Player = Depends(get_current_player),
) -> DownloadCompleteResponse:
    """Fecha o ciclo de verificacao de integridade: o Launcher reporta o
    SHA-256 calculado localmente apos o download, o backend compara contra o
    manifest que autorizou aquele download e marca COMPLETED (bate) ou
    FAILED/checksum_mismatch (nao bate — Launcher deve re-tentar o arquivo)."""
    download_service: DownloadService = request.app.state.download_service
    await enforce_rate_limit(_complete_limiter, str(player.id))
    try:
        download = await download_service.complete_download(
            download_id, player, client_sha256=body.client_sha256, bytes_transferred=body.bytes_transferred
        )
    except DownloadError as exc:
        _raise_from_download_error(exc)
        raise  # pragma: no cover
    return DownloadCompleteResponse(
        download_id=download.id, status=download.status.value, failure_reason=download.failure_reason
    )


@router.post("/update", response_model=UpdateResponse)
async def authorize_update(request: Request, body: UpdateRequest) -> UpdateResponse:
    """Sem auth — o Launcher precisa poder se auto-atualizar antes de o
    usuario conseguir logar. Nao gera registro de Download (binario do
    Launcher nao e um Product), so assina a URL."""
    download_service: DownloadService = request.app.state.download_service
    platform = _parse_platform(body.platform)
    await enforce_rate_limit(_update_limiter, get_client_ip(request) or "unknown")
    try:
        authorization = await download_service.authorize_launcher_update(platform)
    except DownloadError as exc:
        _raise_from_download_error(exc)
        raise  # pragma: no cover
    return UpdateResponse(
        url=authorization.url,
        version=authorization.version,
        sha256=authorization.sha256,
        size_bytes=authorization.size_bytes,
        is_mandatory=authorization.is_mandatory,
        release_notes=authorization.release_notes,
        expires_at=authorization.expires_at.isoformat(),
    )
