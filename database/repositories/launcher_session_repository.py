from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from database.models.launcher_session import LauncherSession
from database.repositories.base_repository import BaseRepository


class LauncherSessionRepository(BaseRepository[LauncherSession]):
    model = LauncherSession

    async def get_by_token_hash(self, refresh_token_hash: str) -> LauncherSession | None:
        result = await self.session.execute(
            select(LauncherSession).where(LauncherSession.refresh_token_hash == refresh_token_hash)
        )
        return result.scalar_one_or_none()

    async def list_active_by_device(self, device_id: uuid.UUID) -> list[LauncherSession]:
        result = await self.session.execute(
            select(LauncherSession).where(
                LauncherSession.device_id == device_id, LauncherSession.revoked_at.is_(None)
            )
        )
        return list(result.scalars().all())

    async def revoke_all_for_device(self, device_id: uuid.UUID, *, reason: str, revoked_at: datetime) -> None:
        """Usada quando um Device e revogado — mata todas as sessoes ativas
        dele de uma vez, em vez de depender do caller iterar."""
        for session_row in await self.list_active_by_device(device_id):
            session_row.revoked_at = revoked_at
            session_row.revoked_reason = reason
        await self.session.flush()
