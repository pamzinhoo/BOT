from __future__ import annotations

from sqlalchemy import select

from database.models.log import LogEntry
from database.repositories.base_repository import BaseRepository


class LogRepository(BaseRepository[LogEntry]):
    model = LogEntry

    async def list_recent(self, guild_id: int, limit: int = 20) -> list[LogEntry]:
        result = await self.session.execute(
            select(LogEntry)
            .where(LogEntry.guild_id == guild_id)
            .order_by(LogEntry.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
