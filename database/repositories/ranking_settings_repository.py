from __future__ import annotations

from sqlalchemy import select

from database.models.ranking_settings import RankingSettings
from database.repositories.base_repository import BaseRepository


class RankingSettingsRepository(BaseRepository[RankingSettings]):
    model = RankingSettings

    async def get_by_guild_id(self, guild_id: int) -> RankingSettings | None:
        result = await self.session.execute(
            select(RankingSettings).where(RankingSettings.guild_id == guild_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, guild_id: int) -> RankingSettings:
        settings = await self.get_by_guild_id(guild_id)
        if settings is not None:
            return settings
        return await self.add(RankingSettings(guild_id=guild_id))
