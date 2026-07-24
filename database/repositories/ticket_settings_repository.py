from __future__ import annotations

from sqlalchemy import select

from database.models.ticket_settings import TicketSettings
from database.repositories.base_repository import BaseRepository


class TicketSettingsRepository(BaseRepository[TicketSettings]):
    model = TicketSettings

    async def get_by_guild_id(self, guild_id: int) -> TicketSettings | None:
        result = await self.session.execute(
            select(TicketSettings).where(TicketSettings.guild_id == guild_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, guild_id: int) -> TicketSettings:
        settings = await self.get_by_guild_id(guild_id)
        if settings is not None:
            return settings
        return await self.add(TicketSettings(guild_id=guild_id))
