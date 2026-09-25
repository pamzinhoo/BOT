from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select

from database.models.event_timer import EventTimer, EventTimerStatus
from database.repositories.base_repository import BaseRepository


class EventTimerRepository(BaseRepository[EventTimer]):
    model = EventTimer

    async def list_by_guild(self, guild_id: int) -> list[EventTimer]:
        result = await self.session.execute(
            select(EventTimer)
            .where(EventTimer.guild_id == guild_id)
            .order_by(EventTimer.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id_locked(self, event_id: uuid.UUID) -> EventTimer | None:
        result = await self.session.execute(
            select(EventTimer).where(EventTimer.id == event_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_due(self, now: datetime) -> list[EventTimer]:
        result = await self.session.execute(
            select(EventTimer).where(
                EventTimer.status == EventTimerStatus.ACTIVE,
                EventTimer.next_announcement_at.is_not(None),
                EventTimer.next_announcement_at <= now,
            )
        )
        return list(result.scalars().all())

    async def list_expired(self, now: datetime) -> list[EventTimer]:
        result = await self.session.execute(
            select(EventTimer).where(
                EventTimer.status.in_([EventTimerStatus.ACTIVE, EventTimerStatus.PAUSED]),
                EventTimer.ends_at <= now,
            )
        )
        return list(result.scalars().all())

    async def list_image_cleanup_pending(self) -> list[EventTimer]:
        result = await self.session.execute(
            select(EventTimer).where(EventTimer.image_delete_pending.is_(True))
        )
        return list(result.scalars().all())

    async def claim_due(self, event_id: uuid.UUID, now: datetime) -> EventTimer | None:
        event = await self.get_by_id_locked(event_id)
        if (
            event is None
            or event.status != EventTimerStatus.ACTIVE
            or event.next_announcement_at is None
            or event.next_announcement_at > now
            or event.ends_at <= now
        ):
            return None
        event.next_announcement_at = min(
            now + timedelta(seconds=event.repeat_interval_seconds),
            event.ends_at,
        )
        await self.session.flush()
        return event
