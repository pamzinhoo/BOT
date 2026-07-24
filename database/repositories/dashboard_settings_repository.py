from __future__ import annotations

from sqlalchemy import select

from database.models.dashboard_settings import DashboardSettings
from database.repositories.base_repository import BaseRepository


class DashboardSettingsRepository(BaseRepository[DashboardSettings]):
    model = DashboardSettings

    async def get_by_guild_id(self, guild_id: int) -> DashboardSettings | None:
        result = await self.session.execute(
            select(DashboardSettings).where(DashboardSettings.guild_id == guild_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, guild_id: int) -> DashboardSettings:
        settings = await self.get_by_guild_id(guild_id)
        if settings is not None:
            return settings
        return await self.add(DashboardSettings(guild_id=guild_id))

    async def list_auto_update_enabled(self) -> list[DashboardSettings]:
        result = await self.session.execute(
            select(DashboardSettings).where(DashboardSettings.auto_update_enabled.is_(True))
        )
        return list(result.scalars().all())
