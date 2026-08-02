from __future__ import annotations

from sqlalchemy import select

from database.models.automod import AutoModLog, AutoModSettings, AutoModWord
from database.repositories.base_repository import BaseRepository


class AutoModWordRepository(BaseRepository[AutoModWord]):
    model = AutoModWord

    async def list_by_guild(self, guild_id: int) -> list[AutoModWord]:
        result = await self.session.execute(
            select(AutoModWord).where(AutoModWord.guild_id == guild_id).order_by(AutoModWord.palavra)
        )
        return list(result.scalars().all())

    async def get_by_word(self, guild_id: int, palavra: str) -> AutoModWord | None:
        result = await self.session.execute(
            select(AutoModWord).where(
                AutoModWord.guild_id == guild_id, AutoModWord.palavra == palavra
            )
        )
        return result.scalar_one_or_none()


class AutoModSettingsRepository(BaseRepository[AutoModSettings]):
    model = AutoModSettings

    async def get_by_guild_id(self, guild_id: int) -> AutoModSettings | None:
        result = await self.session.execute(
            select(AutoModSettings).where(AutoModSettings.guild_id == guild_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, guild_id: int) -> AutoModSettings:
        settings = await self.get_by_guild_id(guild_id)
        if settings is not None:
            return settings
        return await self.add(AutoModSettings(guild_id=guild_id))


class AutoModLogRepository(BaseRepository[AutoModLog]):
    model = AutoModLog

    async def list_recent(self, guild_id: int, limit: int = 20) -> list[AutoModLog]:
        result = await self.session.execute(
            select(AutoModLog)
            .where(AutoModLog.guild_id == guild_id)
            .order_by(AutoModLog.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_by_user(self, guild_id: int, user_id: int, limit: int = 20) -> list[AutoModLog]:
        result = await self.session.execute(
            select(AutoModLog)
            .where(AutoModLog.guild_id == guild_id, AutoModLog.user_id == user_id)
            .order_by(AutoModLog.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
