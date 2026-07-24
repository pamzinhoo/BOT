from __future__ import annotations

import uuid

from sqlalchemy import select

from database.models.staff import Staff
from database.models.staff_stats import StaffStats
from database.repositories.base_repository import BaseRepository


class StaffStatsRepository(BaseRepository[StaffStats]):
    model = StaffStats

    async def get_by_staff_id(self, staff_id: uuid.UUID) -> StaffStats | None:
        result = await self.session.execute(
            select(StaffStats).where(StaffStats.staff_id == staff_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, staff_id: uuid.UUID) -> StaffStats:
        stats = await self.get_by_staff_id(staff_id)
        if stats is not None:
            return stats
        return await self.add(StaffStats(staff_id=staff_id))

    async def list_ranking_by_guild(self, guild_id: int) -> list[tuple[Staff, StaffStats]]:
        result = await self.session.execute(
            select(Staff, StaffStats)
            .join(StaffStats, StaffStats.staff_id == Staff.id)
            .where(Staff.guild_id == guild_id)
            .order_by(StaffStats.tickets_fechados.desc(), StaffStats.avaliacao_media.desc())
        )
        return [(row.Staff, row.StaffStats) for row in result]
