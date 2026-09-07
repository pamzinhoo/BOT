from __future__ import annotations

from fastapi import APIRouter

from api.routes.admin.events_router import router as events_router
from api.routes.admin.router import router as legacy_router
from api.routes.admin.settings_router import router as settings_router

router = APIRouter()
router.include_router(settings_router)
router.include_router(events_router)
router.include_router(legacy_router)

__all__ = ["router"]
