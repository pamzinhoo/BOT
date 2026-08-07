from __future__ import annotations

from sqlalchemy import select

from database.models.launcher_news import LauncherNews
from database.repositories.base_repository import BaseRepository


class LauncherNewsRepository(BaseRepository[LauncherNews]):
    model = LauncherNews

    async def list_published(self, *, limit: int = 20) -> list[LauncherNews]:
        result = await self.session.execute(
            select(LauncherNews)
            .where(LauncherNews.is_published.is_(True), LauncherNews.deleted_at.is_(None))
            .order_by(LauncherNews.published_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
