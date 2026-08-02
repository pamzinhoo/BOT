from __future__ import annotations

from sqlalchemy import select

from database.models.monetization_gateway_settings import MonetizationGatewaySettings
from database.repositories.base_repository import BaseRepository


class MonetizationGatewaySettingsRepository(BaseRepository[MonetizationGatewaySettings]):
    model = MonetizationGatewaySettings

    async def get_by_guild_id(self, guild_id: int) -> MonetizationGatewaySettings | None:
        result = await self.session.execute(
            select(MonetizationGatewaySettings).where(MonetizationGatewaySettings.guild_id == guild_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, guild_id: int) -> MonetizationGatewaySettings:
        settings = await self.get_by_guild_id(guild_id)
        if settings is not None:
            return settings
        return await self.add(MonetizationGatewaySettings(guild_id=guild_id))
