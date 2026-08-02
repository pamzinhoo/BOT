from __future__ import annotations

from sqlalchemy import select

from database.models.enquete_settings import EnqueteSettings
from database.repositories.base_repository import BaseRepository


class EnqueteSettingsRepository(BaseRepository[EnqueteSettings]):
    model = EnqueteSettings

    async def get_by_guild_id(self, guild_id: int) -> EnqueteSettings | None:
        result = await self.session.execute(
            select(EnqueteSettings).where(EnqueteSettings.guild_id == guild_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, guild_id: int) -> EnqueteSettings:
        settings = await self.get_by_guild_id(guild_id)
        if settings is not None:
            return settings
        return await self.add(EnqueteSettings(guild_id=guild_id))
