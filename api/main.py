from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes.auth_routes import router as auth_router
from api.routes.download_routes import router as download_router
from api.routes.health_routes import router as health_router
from api.routes.internal_routes import router as internal_router
from api.routes.launcher_routes import router as launcher_router
from api.routes.player_routes import router as player_router
from api.routes.webhook_routes import router as webhook_router
from core.logger import get_logger
from providers.storage.base import StorageProvider
from services.auth_service import AuthService
from services.download_service import DownloadService
from services.launcher_content_service import LauncherContentService
from services.webhook_service import WebhookService

if TYPE_CHECKING:
    from core.bot import LimerenceBot

logger = get_logger("api")


def _build_storage_provider(bot: LimerenceBot) -> StorageProvider | None:
    settings = bot.settings
    if not settings.storage_configured:
        logger.warning(
            "Storage (STORAGE_BUCKET/STORAGE_ACCESS_KEY_ID/STORAGE_SECRET_ACCESS_KEY) nao "
            "configurado — /download e /update responderao 503 ate configurar."
        )
        return None
    from providers.storage.s3_compatible import S3CompatibleStorageProvider

    return S3CompatibleStorageProvider(
        name=settings.storage_provider,
        bucket=settings.storage_bucket,  # type: ignore[arg-type]
        access_key_id=settings.storage_access_key_id,  # type: ignore[arg-type]
        secret_access_key=settings.storage_secret_access_key,  # type: ignore[arg-type]
        endpoint_url=settings.storage_endpoint_url,
        region_name=settings.storage_region,
    )


def create_app(bot: LimerenceBot) -> FastAPI:
    if not bot.settings.internal_api_configured:
        logger.warning(
            "INTERNAL_API_SECRET nao configurado — /internal/* responderao 503 ate configurar."
        )

    app = FastAPI(title="Limerence Bot API", docs_url=None, redoc_url=None)

    # CORS explicito, negando toda origem por padrao (Launcher e Tauri, fala
    # Bearer token, nao navegador/cookie — nao precisa de CORS aberto).
    # CORS_ALLOWED_ORIGINS so existe pra um eventual frontend web (ex.:
    # painel staff) chamando esta API direto do navegador; sem ele, um site
    # de terceiro nao consegue nem ler a resposta de um XHR/fetch pra ca.
    if bot.settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(bot.settings.cors_allowed_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )

    app.state.bot = bot
    app.state.webhook_service = WebhookService(
        bot.database, bot.payment_service, bot.subscription_service, bot.settings
    )
    app.state.auth_service = AuthService(bot.database, bot.settings)
    app.state.product_service = bot.product_service
    app.state.license_service = bot.license_service
    app.state.dlc_service = bot.dlc_service
    app.state.launcher_content_service = LauncherContentService(bot.database)
    app.state.download_service = DownloadService(
        bot.database, bot.license_service, _build_storage_provider(bot), bot.settings
    )
    app.include_router(health_router)
    app.include_router(webhook_router)
    app.include_router(auth_router)
    app.include_router(launcher_router)
    app.include_router(player_router)
    app.include_router(download_router)
    app.include_router(internal_router)
    return app
