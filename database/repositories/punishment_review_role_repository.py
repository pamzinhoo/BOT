from __future__ import annotations

import uuid

from sqlalchemy import delete, select

from database.models.punishment_review_role import PunishmentReviewRole
from database.repositories.base_repository import BaseRepository


class PunishmentReviewRoleRepository(BaseRepository[PunishmentReviewRole]):
    model = PunishmentReviewRole

    async def list_by_punishment(self, punishment_id: uuid.UUID) -> list[PunishmentReviewRole]:
        result = await self.session.execute(
            select(PunishmentReviewRole).where(PunishmentReviewRole.punishment_id == punishment_id)
        )
        return list(result.scalars().all())

    async def delete_by_punishment(self, punishment_id: uuid.UUID) -> None:
        await self.session.execute(
            delete(PunishmentReviewRole).where(PunishmentReviewRole.punishment_id == punishment_id)
        )
