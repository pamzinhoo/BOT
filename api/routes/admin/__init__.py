from __future__ import annotations

from fastapi import APIRouter

from api.routes.admin.dlcs_router import router as dlcs_router
from api.routes.admin.events_router import router as events_router
from api.routes.admin.giveaways_router import router as giveaways_router
from api.routes.admin.monetization_plans_router import router as monetization_plans_router
from api.routes.admin.monetization_router import router as monetization_router
from api.routes.admin.panels_router import router as panels_router
from api.routes.admin.router import router as legacy_router
from api.routes.admin.settings_emoji_router import router as settings_emoji_router
from api.routes.admin.settings_patch_router import router as settings_patch_router
from api.routes.admin.settings_router import router as settings_router
from api.routes.admin.staff_router import router as staff_router
from api.routes.admin.ticket_actions_router import router as ticket_actions_router

router = APIRouter()
router.include_router(settings_emoji_router)
router.include_router(settings_patch_router)
router.include_router(settings_router)
router.include_router(events_router)
router.include_router(giveaways_router)
router.include_router(dlcs_router)
router.include_router(panels_router)
router.include_router(monetization_plans_router)
router.include_router(monetization_router)
router.include_router(staff_router)
router.include_router(ticket_actions_router)
router.include_router(legacy_router)

__all__ = ["router"]
