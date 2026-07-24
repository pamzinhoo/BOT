from __future__ import annotations

from sqlalchemy import select

from database.models.anti_spam_settings import AntiSpamSettings
from database.repositories.base_repository import BaseRepository


class AntiSpamSettingsRepository(BaseRepository[AntiSpamSettings]):
    model = AntiSpamSettings

    async def get_by_guild_id(self, guild_id: int) -> AntiSpamSettings | None:
        result = await self.session.execute(
            select(AntiSpamSettings).where(AntiSpamSettings.guild_id == guild_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, guild_id: int) -> AntiSpamSettings:
        settings = await self.get_by_guild_id(guild_id)
        if settings is not None:
            return settings
        return await self.add(AntiSpamSettings(guild_id=guild_id))
