from __future__ import annotations

from sqlalchemy import select

from database.models.monetization_settings import MonetizationSettings
from database.repositories.base_repository import BaseRepository


class MonetizationSettingsRepository(BaseRepository[MonetizationSettings]):
    model = MonetizationSettings

    async def get_by_guild_id(self, guild_id: int) -> MonetizationSettings | None:
        result = await self.session.execute(
            select(MonetizationSettings).where(MonetizationSettings.guild_id == guild_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, guild_id: int) -> MonetizationSettings:
        settings = await self.get_by_guild_id(guild_id)
        if settings is not None:
            return settings
        return await self.add(MonetizationSettings(guild_id=guild_id))
