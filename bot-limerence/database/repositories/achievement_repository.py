from __future__ import annotations

import uuid

from sqlalchemy import select

from database.models.achievement import Achievement
from database.repositories.base_repository import BaseRepository


class AchievementRepository(BaseRepository[Achievement]):
    model = Achievement

    async def exists(self, staff_id: uuid.UUID, key: str) -> bool:
        result = await self.session.execute(
            select(Achievement.id).where(Achievement.staff_id == staff_id, Achievement.key == key)
        )
        return result.scalar_one_or_none() is not None

    async def award(self, staff_id: uuid.UUID, key: str) -> bool:
        """Concede a conquista se ainda nao tiver. True se acabou de desbloquear."""
        if await self.exists(staff_id, key):
            return False
        await self.add(Achievement(staff_id=staff_id, key=key))
        return True

    async def list_by_staff(self, staff_id: uuid.UUID) -> list[Achievement]:
        result = await self.session.execute(
            select(Achievement).where(Achievement.staff_id == staff_id).order_by(Achievement.created_at)
        )
        return list(result.scalars().all())
