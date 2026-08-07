from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Request

from api.dependencies import enforce_rate_limit, get_client_ip, verify_internal_signature
from api.schemas.internal import (
    GuildReconciliationResultResponse,
    LicenseEventRequest,
    ReconciliationReportResponse,
)
from core.events import LicenseEventPayload
from core.logger import get_logger
from core.rate_limiter import RateLimiter

if TYPE_CHECKING:
    from core.bot import LimerenceBot

logger = get_logger("internal_routes")

# Defesa em profundidade: mesmo autenticado por HMAC, /internal/* nao fica
# sem limite — um chamador legitimo comprometido (ou bug em loop) nao deve
# conseguir martelar reconciliacao/eventos sem freio.
_internal_limiter = RateLimiter(max_hits=120, window_seconds=60)


async def _enforce_internal_rate_limit(request: Request) -> None:
    await enforce_rate_limit(_internal_limiter, get_client_ip(request) or "unknown")


router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(verify_internal_signature), Depends(_enforce_internal_rate_limit)],
)


@router.post("/license-events", status_code=204)
async def receive_license_event(request: Request, body: LicenseEventRequest) -> None:
    """Canal HTTP autenticado (HMAC) Backend<->Bot da Fase 5 — equivalente ao
    EventBus in-process (core/event_bus.py), pro caso de Backend e Bot
    rodarem como processos separados no futuro. Despacha direto pro
    RoleSyncService, sem passar pelo EventBus (o payload ja e o evento
    final, nao precisa de pub/sub de novo dentro do mesmo processo)."""
    bot: LimerenceBot = request.app.state.bot
    payload = LicenseEventPayload(
        license_id=body.license_id,
        player_id=body.player_id,
        product_id=body.product_id,
        status=body.status,
        event_type=body.event_type,
        occurred_at=body.occurred_at,
    )
    await bot.role_sync_service.handle_license_event(payload)


@router.post("/reconcile", response_model=ReconciliationReportResponse)
async def trigger_reconciliation(request: Request) -> ReconciliationReportResponse:
    """Reconciliacao sob demanda (alem do ciclo periodico do
    LicenseReconciliationCog) — util pra staff/backend forcar uma correcao
    imediata sem esperar o proximo tick."""
    bot: LimerenceBot = request.app.state.bot
    report = await bot.reconciliation_service.reconcile_all_guilds()
    return ReconciliationReportResponse(
        guilds_checked=report.guilds_checked,
        roles_granted=report.roles_granted,
        roles_removed=report.roles_removed,
        errors=report.errors,
        per_guild=[
            GuildReconciliationResultResponse(
                guild_id=r.guild_id, roles_granted=r.roles_granted, roles_removed=r.roles_removed, errors=r.errors
            )
            for r in report.per_guild
        ],
    )
