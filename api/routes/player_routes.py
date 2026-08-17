from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request

from api.dependencies import enforce_rate_limit, get_current_player
from api.schemas.launcher import (
    DlcCatalogItemResponse,
    DlcPurchaseResponse,
    LicenseResponse,
    ProductCatalogItemResponse,
)
from core.rate_limiter import RateLimiter
from database.models.license import LicenseStatus
from services.dlc_service import DlcError
from services.subscription_service import DuplicateSubscriptionError, MissingPriceError

if TYPE_CHECKING:
    from database.models.player import Player
    from services.dlc_service import DlcService
    from services.license_service import LicenseService
    from services.product_service import ProductService

router = APIRouter(prefix="/player", tags=["player"])

_read_limiter = RateLimiter(max_hits=60, window_seconds=60)
_purchase_limiter = RateLimiter(max_hits=10, window_seconds=60)


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
    products_by_id = {
        product.id: product
        for product in await product_service.list_by_ids(
            [lic.product_id for lic in license_rows], include_deleted=True
        )
    }
    responses: list[LicenseResponse] = []
    for lic in license_rows:
        product = products_by_id.get(lic.product_id)
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


@router.get("/dlcs", response_model=list[DlcCatalogItemResponse])
async def dlcs(request: Request, player: Player = Depends(get_current_player)) -> list[DlcCatalogItemResponse]:
    """Catálogo de DLC do jogo Limerence — variante de `/player/products`
    filtrada a `product_type=DLC`. `unlocked` é sempre derivado de License
    ACTIVE (nunca um campo que o cliente possa forjar): DLC gratuita tem a
    License mantida em sincronia com o cargo Discord (cogs/dlc.py +
    DlcService.reconcile_guild); DLC paga tem a License concedida só após
    pagamento aprovado (pipeline de Plano já existente)."""
    await enforce_rate_limit(_read_limiter, str(player.id))
    dlc_service: DlcService = request.app.state.dlc_service
    license_service: LicenseService = request.app.state.license_service

    catalog = await dlc_service.list_dlcs(only_active=True)
    license_rows = await license_service.list_by_player(player.id)
    license_by_product = {lic.product_id: lic for lic in license_rows}

    responses: list[DlcCatalogItemResponse] = []
    for product in catalog:
        lic = license_by_product.get(product.id)
        responses.append(
            DlcCatalogItemResponse(
                id=product.id,
                slug=product.slug,
                name=product.name,
                description=product.description,
                access_type="free" if dlc_service.is_free(product) else "paid",
                price_amount=product.price_amount,
                currency=product.currency,
                unlocked=lic is not None and lic.status == LicenseStatus.ACTIVE,
                license_status=lic.status.value if lic else None,
            )
        )
    return responses


@router.post("/dlcs/{product_id}/purchase", response_model=DlcPurchaseResponse)
async def purchase_dlc(
    product_id: uuid.UUID, request: Request, player: Player = Depends(get_current_player)
) -> DlcPurchaseResponse:
    """Inicia a compra de uma DLC paga. O preço cobrado vem sempre do `Plan`
    lido do banco (nunca do corpo da requisição — não há campo de preço pra
    manipular). Só cria a cobrança (PIX/checkout); a aprovação continua vindo
    do webhook do Mercado Pago, mesmo pipeline de sempre
    (SubscriptionService.confirm_payment) — este endpoint nunca concede a
    License diretamente."""
    await enforce_rate_limit(_purchase_limiter, str(player.id))
    dlc_service: DlcService = request.app.state.dlc_service
    try:
        _subscription, payment, result = await dlc_service.start_purchase(product_id, player.discord_id)
    except DlcError as exc:
        raise HTTPException(
            status_code=422, detail={"error": "dlc_purchase_error", "message": str(exc)}
        ) from exc
    except DuplicateSubscriptionError as exc:
        raise HTTPException(
            status_code=409, detail={"error": "duplicate_purchase", "message": str(exc)}
        ) from exc
    except MissingPriceError as exc:
        raise HTTPException(
            status_code=422, detail={"error": "missing_price", "message": str(exc)}
        ) from exc

    return DlcPurchaseResponse(
        payment_id=payment.id,
        status=result.status.value,
        checkout_url=result.checkout_url,
        qr_code=result.qr_code,
        qr_code_base64=result.qr_code_base64,
        expires_at=_iso(result.expires_at),
    )
