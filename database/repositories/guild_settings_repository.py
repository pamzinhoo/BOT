from __future__ import annotations

from sqlalchemy import select

from database.models.guild_settings import GuildSettings
from database.repositories.base_repository import BaseRepository


class GuildSettingsRepository(BaseRepository[GuildSettings]):
    model = GuildSettings

    async def get_by_guild_id(self, guild_id: int) -> GuildSettings | None:
        result = await self.session.execute(
            select(GuildSettings).where(GuildSettings.guild_id == guild_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, guild_id: int) -> GuildSettings:
        settings = await self.get_by_guild_id(guild_id)
        if settings is not None:
            return settings
        return await self.add(GuildSettings(guild_id=guild_id))

    async def list_with_verified_role(self) -> list[GuildSettings]:
        result = await self.session.execute(
            select(GuildSettings).where(GuildSettings.verified_role_id.is_not(None))
        )
        return list(result.scalars().all())
