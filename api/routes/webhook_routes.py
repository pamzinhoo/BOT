from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.logger import get_logger
from providers.base import PaymentGatewayError

if TYPE_CHECKING:
    from core.bot import LimerenceBot
    from services.webhook_service import WebhookService

logger = get_logger("webhook_routes")

router = APIRouter()


@router.post("/webhooks/mercadopago")
async def mercadopago_webhook(request: Request) -> JSONResponse:
    bot: "LimerenceBot" = request.app.state.bot
    webhook_service: "WebhookService" = request.app.state.webhook_service

    if not bot.settings.webhook_enabled:
        logger.warning(
            "Webhook recebido mas WEBHOOK_ENABLED=false — ignorando (modo desenvolvimento)."
        )
        return JSONResponse({"status": "ignored_dev_mode"}, status_code=200)

    raw_body = await request.body()
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"status": "invalid_body"}, status_code=400)

    headers = {key.lower(): value for key, value in request.headers.items()}

    try:
        await webhook_service.handle_mercadopago_notification(payload, headers, raw_body)
    except PaymentGatewayError:
        logger.exception("Erro de gateway ao processar webhook — Mercado Pago vai tentar de novo.")
        return JSONResponse({"status": "gateway_error"}, status_code=500)
    except Exception:
        logger.exception("Erro inesperado ao processar webhook — Mercado Pago vai tentar de novo.")
        return JSONResponse({"status": "internal_error"}, status_code=500)

    return JSONResponse({"status": "processed"}, status_code=200)
