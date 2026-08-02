from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI

from api.routes.health_routes import router as health_router
from api.routes.webhook_routes import router as webhook_router
from services.webhook_service import WebhookService

if TYPE_CHECKING:
    from core.bot import LimerenceBot


def create_app(bot: "LimerenceBot") -> FastAPI:
    app = FastAPI(title="Limerence Bot API", docs_url=None, redoc_url=None)
    app.state.bot = bot
    app.state.webhook_service = WebhookService(
        bot.database, bot.payment_service, bot.subscription_service, bot.settings
    )
    app.include_router(health_router)
    app.include_router(webhook_router)
    return app
