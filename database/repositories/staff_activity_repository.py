from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from database.models.staff_activity import StaffActivity, StaffActivityEvent
from database.repositories.base_repository import BaseRepository


class StaffActivityRepository(BaseRepository[StaffActivity]):
    model = StaffActivity

    async def log_event(
        self, staff_id: uuid.UUID, event_type: StaffActivityEvent, occurred_at: datetime
    ) -> StaffActivity:
        return await self.add(
            StaffActivity(staff_id=staff_id, event_type=event_type, occurred_at=occurred_at)
        )

    async def list_recent(self, staff_id: uuid.UUID, limit: int = 20) -> list[StaffActivity]:
        result = await self.session.execute(
            select(StaffActivity)
            .where(StaffActivity.staff_id == staff_id)
            .order_by(StaffActivity.occurred_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
