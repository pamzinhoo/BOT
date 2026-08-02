from __future__ import annotations

from sqlalchemy import select

from database.models.verification_settings import VerificationSettings
from database.repositories.base_repository import BaseRepository


class VerificationSettingsRepository(BaseRepository[VerificationSettings]):
    model = VerificationSettings

    async def get_by_guild_id(self, guild_id: int) -> VerificationSettings | None:
        result = await self.session.execute(
            select(VerificationSettings).where(VerificationSettings.guild_id == guild_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, guild_id: int) -> VerificationSettings:
        settings = await self.get_by_guild_id(guild_id)
        if settings is not None:
            return settings
        return await self.add(VerificationSettings(guild_id=guild_id))
