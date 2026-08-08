from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class LicenseEventRequest(BaseModel):
    """Espelha core.events.LicenseEventPayload — formato que um Backend
    desacoplado do processo do bot usaria pra empurrar um evento de licenca
    via HTTP em vez de EventBus in-process."""

    license_id: uuid.UUID
    player_id: uuid.UUID
    product_id: uuid.UUID
    status: str
    event_type: str
    occurred_at: datetime


class PlayerVerifiedRequest(BaseModel):
    """Disparado pelo Backend apos um login com Discord bem-sucedido no
    launcher (ver providers/internal_events_client.py::notify_player_verified
    no repo do backend)."""

    discord_id: int


class GuildReconciliationResultResponse(BaseModel):
    guild_id: int
    roles_granted: int
    roles_removed: int
    errors: int


class ReconciliationReportResponse(BaseModel):
    guilds_checked: int
    roles_granted: int
    roles_removed: int
    errors: int
    per_guild: list[GuildReconciliationResultResponse]
