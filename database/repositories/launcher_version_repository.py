from __future__ import annotations

from sqlalchemy import select

from database.models.launcher_version import LauncherPlatform, LauncherVersion
from database.repositories.base_repository import BaseRepository


class LauncherVersionRepository(BaseRepository[LauncherVersion]):
    model = LauncherVersion

    async def get_current(self, platform: LauncherPlatform) -> LauncherVersion | None:
        result = await self.session.execute(
            select(LauncherVersion).where(
                LauncherVersion.platform == platform, LauncherVersion.is_current.is_(True)
            )
        )
        return result.scalar_one_or_none()

    async def set_current(self, platform: LauncherPlatform, version: LauncherVersion) -> None:
        result = await self.session.execute(
            select(LauncherVersion).where(
                LauncherVersion.platform == platform, LauncherVersion.is_current.is_(True)
            )
        )
        for previous in result.scalars().all():
            previous.is_current = False
        version.is_current = True
        await self.session.flush()
