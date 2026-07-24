from __future__ import annotations

from sqlalchemy import select

from database.models.permission_settings import PermissionSettings
from database.repositories.base_repository import BaseRepository


class PermissionSettingsRepository(BaseRepository[PermissionSettings]):
    model = PermissionSettings

    async def get_by_guild_id(self, guild_id: int) -> PermissionSettings | None:
        result = await self.session.execute(
            select(PermissionSettings).where(PermissionSettings.guild_id == guild_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, guild_id: int) -> PermissionSettings:
        settings = await self.get_by_guild_id(guild_id)
        if settings is not None:
            return settings
        return await self.add(PermissionSettings(guild_id=guild_id))
