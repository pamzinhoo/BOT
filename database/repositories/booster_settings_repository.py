from __future__ import annotations

from sqlalchemy import select

from database.models.booster_settings import BoosterSettings
from database.repositories.base_repository import BaseRepository


class BoosterSettingsRepository(BaseRepository[BoosterSettings]):
    model = BoosterSettings

    async def get_by_guild_id(self, guild_id: int) -> BoosterSettings | None:
        result = await self.session.execute(
            select(BoosterSettings).where(BoosterSettings.guild_id == guild_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, guild_id: int) -> BoosterSettings:
        settings = await self.get_by_guild_id(guild_id)
        if settings is not None:
            return settings
        return await self.add(BoosterSettings(guild_id=guild_id))
