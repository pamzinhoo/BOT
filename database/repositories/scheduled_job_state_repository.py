from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from database.models.scheduled_job_state import ScheduledJobState
from database.repositories.base_repository import BaseRepository


class ScheduledJobStateRepository(BaseRepository[ScheduledJobState]):
    model = ScheduledJobState

    async def try_begin_daily(
        self,
        guild_id: int,
        job_name: str,
        *,
        period_start: datetime,
        now: datetime,
        lease: timedelta,
    ) -> bool:
        stale_before = now - lease
        stmt = (
            insert(ScheduledJobState)
            .values(guild_id=guild_id, job_name=job_name, last_attempt_at=now)
            .on_conflict_do_update(
                index_elements=[ScheduledJobState.guild_id, ScheduledJobState.job_name],
                set_={"last_attempt_at": now},
                where=(
                    (
                        ScheduledJobState.last_success_at.is_(None)
                        | (ScheduledJobState.last_success_at < period_start)
                    )
                    & (
                        ScheduledJobState.last_attempt_at.is_(None)
                        | (ScheduledJobState.last_attempt_at < stale_before)
                    )
                ),
            )
            .returning(ScheduledJobState.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def mark_success(self, guild_id: int, job_name: str, *, finished_at: datetime) -> None:
        await self.session.execute(
            update(ScheduledJobState)
            .where(
                ScheduledJobState.guild_id == guild_id,
                ScheduledJobState.job_name == job_name,
            )
            .values(last_success_at=finished_at, last_attempt_at=finished_at)
        )

    async def get_state(self, guild_id: int, job_name: str) -> ScheduledJobState | None:
        result = await self.session.execute(
            select(ScheduledJobState).where(
                ScheduledJobState.guild_id == guild_id,
                ScheduledJobState.job_name == job_name,
            )
        )
        return result.scalar_one_or_none()
