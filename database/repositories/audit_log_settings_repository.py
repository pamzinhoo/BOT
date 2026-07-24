from __future__ import annotations

from sqlalchemy import select

from database.models.audit_log_settings import AuditLogSettings
from database.repositories.base_repository import BaseRepository


class AuditLogSettingsRepository(BaseRepository[AuditLogSettings]):
    model = AuditLogSettings

    async def get_by_guild_id(self, guild_id: int) -> AuditLogSettings | None:
        result = await self.session.execute(
            select(AuditLogSettings).where(AuditLogSettings.guild_id == guild_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, guild_id: int) -> AuditLogSettings:
        settings = await self.get_by_guild_id(guild_id)
        if settings is not None:
            return settings
        return await self.add(AuditLogSettings(guild_id=guild_id))
