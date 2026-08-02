from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request

if TYPE_CHECKING:
    from core.bot import LimerenceBot

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict[str, object]:
    bot: "LimerenceBot" = request.app.state.bot
    return {"status": "ok", "environment": bot.settings.environment}


@router.get("/payments/status")
async def payments_status(request: Request) -> dict[str, object]:
    bot: "LimerenceBot" = request.app.state.bot
    return {
        "webhook_enabled": bot.settings.webhook_enabled,
        "payment_mode": bot.settings.payment_mode,
    }
