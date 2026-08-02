from __future__ import annotations

from sqlalchemy import select

from database.models.payment_dm_settings import PaymentDmSettings
from database.repositories.base_repository import BaseRepository


class PaymentDmSettingsRepository(BaseRepository[PaymentDmSettings]):
    model = PaymentDmSettings

    async def get_by_guild_id(self, guild_id: int) -> PaymentDmSettings | None:
        result = await self.session.execute(
            select(PaymentDmSettings).where(PaymentDmSettings.guild_id == guild_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, guild_id: int) -> PaymentDmSettings:
        settings = await self.get_by_guild_id(guild_id)
        if settings is not None:
            return settings
        return await self.add(PaymentDmSettings(guild_id=guild_id))
