from __future__ import annotations

from sqlalchemy import select

from database.models.evaluation_settings import EvaluationSettings
from database.repositories.base_repository import BaseRepository


class EvaluationSettingsRepository(BaseRepository[EvaluationSettings]):
    model = EvaluationSettings

    async def get_by_guild_id(self, guild_id: int) -> EvaluationSettings | None:
        result = await self.session.execute(
            select(EvaluationSettings).where(EvaluationSettings.guild_id == guild_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, guild_id: int) -> EvaluationSettings:
        settings = await self.get_by_guild_id(guild_id)
        if settings is not None:
            return settings
        return await self.add(EvaluationSettings(guild_id=guild_id))
