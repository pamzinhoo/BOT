from __future__ import annotations

import uuid

from database.models.audit_log_launcher import AuditLogLauncher, AuditLogLauncherAction
from database.repositories.base_repository import BaseRepository


class AuditLogLauncherRepository(BaseRepository[AuditLogLauncher]):
    model = AuditLogLauncher

    async def record(
        self,
        *,
        action: AuditLogLauncherAction,
        player_id: uuid.UUID | None = None,
        device_id: uuid.UUID | None = None,
        ip_address: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> AuditLogLauncher:
        entry = AuditLogLauncher(
            action=action,
            player_id=player_id,
            device_id=device_id,
            ip_address=ip_address,
            audit_metadata=metadata or {},
        )
        return await self.add(entry)
