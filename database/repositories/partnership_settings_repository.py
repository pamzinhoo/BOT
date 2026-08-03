from __future__ import annotations

from sqlalchemy import select

from database.models.partnership_settings import PartnershipSettings
from database.repositories.base_repository import BaseRepository


class PartnershipSettingsRepository(BaseRepository[PartnershipSettings]):
    model = PartnershipSettings

    async def get_by_guild_id(self, guild_id: int) -> PartnershipSettings | None:
        result = await self.session.execute(
            select(PartnershipSettings).where(PartnershipSettings.guild_id == guild_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, guild_id: int) -> PartnershipSettings:
        settings = await self.get_by_guild_id(guild_id)
        if settings is not None:
            return settings
        return await self.add(PartnershipSettings(guild_id=guild_id))
