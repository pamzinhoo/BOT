from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Request

from api.dependencies import enforce_rate_limit, get_current_player
from api.schemas.launcher import LicenseResponse, ProductCatalogItemResponse
from core.rate_limiter import RateLimiter
from database.models.license import LicenseStatus

if TYPE_CHECKING:
    from database.models.player import Player
    from services.license_service import LicenseService
    from services.product_service import ProductService

router = APIRouter(prefix="/player", tags=["player"])

_read_limiter = RateLimiter(max_hits=60, window_seconds=60)


def _iso(value: object) -> str | None:
    return value.isoformat() if value is not None else None  # type: ignore[union-attr]


@router.get("/licenses", response_model=list[LicenseResponse])
async def licenses(request: Request, player: Player = Depends(get_current_player)) -> list[LicenseResponse]:
    """Inventario completo do player — inclui licenca revogada/expirada
    (historico), nao so ativa. `/player/products` e que filtra por posse."""
    await enforce_rate_limit(_read_limiter, str(player.id))
    license_service: LicenseService = request.app.state.license_service
    product_service: ProductService = request.app.state.product_service

    license_rows = await license_service.list_by_player(player.id)
    responses: list[LicenseResponse] = []
    for lic in license_rows:
        product = await product_service.get(lic.product_id, include_deleted=True)
        responses.append(
            LicenseResponse(
                id=lic.id,
                product_id=lic.product_id,
                product_slug=product.slug if product else None,
                product_name=product.name if product else None,
                status=lic.status.value,
                purchase_source=lic.purchase_source,
                activated_at=_iso(lic.activated_at),
                expires_at=_iso(lic.expires_at),
                auto_renew=lic.auto_renew,
                revoked_at=_iso(lic.revoked_at),
                revoked_reason=lic.revoked_reason,
            )
        )
    return responses


@router.get("/products", response_model=list[ProductCatalogItemResponse])
async def products(
    request: Request, player: Player = Depends(get_current_player)
) -> list[ProductCatalogItemResponse]:
    """Catalogo ativo (loja/biblioteca) anotado com posse do player — `owned`
    reflete License ACTIVE, nao so a existencia de uma linha (revogada/
    expirada conta como nao-owned aqui)."""
    await enforce_rate_limit(_read_limiter, str(player.id))
    license_service: LicenseService = request.app.state.license_service
    product_service: ProductService = request.app.state.product_service

    catalog = await product_service.list_catalog(only_active=True)
    license_rows = await license_service.list_by_player(player.id)
    license_by_product = {lic.product_id: lic for lic in license_rows}

    responses: list[ProductCatalogItemResponse] = []
    for product in catalog:
        lic = license_by_product.get(product.id)
        responses.append(
            ProductCatalogItemResponse(
                id=product.id,
                slug=product.slug,
                name=product.name,
                product_type=product.product_type.value,
                description=product.description,
                price_amount=product.price_amount,
                currency=product.currency,
                owned=lic is not None and lic.status == LicenseStatus.ACTIVE,
                license_status=lic.status.value if lic else None,
            )
        )
    return responses
