from __future__ import annotations

from sqlalchemy import select

from database.models.pix_manual_settings import PixManualSettings
from database.repositories.base_repository import BaseRepository


class PixManualSettingsRepository(BaseRepository[PixManualSettings]):
    model = PixManualSettings

    async def get_by_guild_id(self, guild_id: int) -> PixManualSettings | None:
        result = await self.session.execute(
            select(PixManualSettings).where(PixManualSettings.guild_id == guild_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, guild_id: int) -> PixManualSettings:
        settings = await self.get_by_guild_id(guild_id)
        if settings is not None:
            return settings
        return await self.add(PixManualSettings(guild_id=guild_id))
