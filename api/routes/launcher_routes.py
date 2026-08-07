from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from api.dependencies import enforce_rate_limit, get_client_ip, get_current_player
from api.schemas.launcher import LauncherVersionResponse, ManifestResponse, NewsItemResponse
from core.rate_limiter import RateLimiter
from database.models.game_manifest import ManifestEntryType
from database.models.launcher_version import LauncherPlatform

if TYPE_CHECKING:
    from database.models.player import Player
    from services.launcher_content_service import LauncherContentService
    from services.license_service import LicenseService

router = APIRouter(prefix="/launcher", tags=["launcher"])

# news/version sao publicas (sem auth) — limite por IP. manifest e
# autenticado — limite por player, mais generoso.
_public_limiter = RateLimiter(max_hits=60, window_seconds=60)
_manifest_limiter = RateLimiter(max_hits=60, window_seconds=60)


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


@router.get("/news", response_model=list[NewsItemResponse])
async def news(request: Request, limit: int = Query(default=20, ge=1, le=100)) -> list[NewsItemResponse]:
    """Publico, sem auth — exibido na tela inicial do Launcher antes do login."""
    await enforce_rate_limit(_public_limiter, get_client_ip(request) or "unknown")
    content_service: LauncherContentService = request.app.state.launcher_content_service
    items = await content_service.list_news(limit=limit)
    return [
        NewsItemResponse(
            id=item.id,
            title=item.title,
            content=item.content,
            cover_image_url=item.cover_image_url,
            published_at=item.published_at.isoformat() if item.published_at else None,
        )
        for item in items
    ]


@router.get("/version", response_model=LauncherVersionResponse)
async def version(request: Request, platform: str = Query(...)) -> LauncherVersionResponse:
    """Publico, sem auth — o Launcher precisa checar se ele mesmo esta
    desatualizado antes de o usuario conseguir logar."""
    await enforce_rate_limit(_public_limiter, get_client_ip(request) or "unknown")
    content_service: LauncherContentService = request.app.state.launcher_content_service
    platform_enum = _parse_platform(platform)
    current = await content_service.get_launcher_version(platform_enum)
    if current is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "version_not_found", "message": "Nenhuma versao publicada para esta plataforma."},
        )
    return LauncherVersionResponse(
        platform=platform_enum.value,
        version=current.version,
        sha256=current.sha256,
        size_bytes=current.size_bytes,
        is_mandatory=current.is_mandatory,
        release_notes=current.release_notes,
    )


@router.get("/manifest", response_model=ManifestResponse)
async def manifest(
    request: Request,
    product_id: uuid.UUID = Query(...),
    entry_type: str = Query(default="full"),
    player: Player = Depends(get_current_player),
) -> ManifestResponse:
    """Requer auth + License ACTIVE no produto — o manifest descreve conteudo
    pago, entao nao e exposto pra quem nao tem direito de baixar (a URL de
    download em si so sai de POST /download, com checagem de novo)."""
    await enforce_rate_limit(_manifest_limiter, str(player.id))
    content_service: LauncherContentService = request.app.state.launcher_content_service
    license_service: LicenseService = request.app.state.license_service
    entry_type_enum = _parse_entry_type(entry_type)

    has_license = await license_service.has_active_license(player.id, product_id)
    if not has_license:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "license_required", "message": "Nenhuma licenca ativa para este produto."},
        )

    entry = await content_service.get_manifest(product_id, entry_type=entry_type_enum)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "manifest_not_found", "message": "Nenhuma versao publicada para este produto."},
        )
    return ManifestResponse(
        product_id=entry.product_id,
        entry_type=entry.entry_type.value,
        version=entry.version,
        sha256=entry.sha256,
        size_bytes=entry.size_bytes,
        depends_on=list(entry.depends_on),
        release_notes=entry.release_notes,
    )
