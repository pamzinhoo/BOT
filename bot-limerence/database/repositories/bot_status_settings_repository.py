from __future__ import annotations

from sqlalchemy import select

from database.models.bot_status_settings import BotStatusSettings
from database.repositories.base_repository import BaseRepository


class BotStatusSettingsRepository(BaseRepository[BotStatusSettings]):
    model = BotStatusSettings

    async def get_by_guild_id(self, guild_id: int) -> BotStatusSettings | None:
        result = await self.session.execute(
            select(BotStatusSettings).where(BotStatusSettings.guild_id == guild_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, guild_id: int) -> BotStatusSettings:
        settings = await self.get_by_guild_id(guild_id)
        if settings is not None:
            return settings
        return await self.add(BotStatusSettings(guild_id=guild_id))

    async def list_with_channel(self) -> list[BotStatusSettings]:
        result = await self.session.execute(
            select(BotStatusSettings).where(BotStatusSettings.channel_id.is_not(None))
        )
        return list(result.scalars().all())
