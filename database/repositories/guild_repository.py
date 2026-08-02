from __future__ import annotations

from sqlalchemy import select

from database.models.guild import Guild
from database.repositories.base_repository import BaseRepository


class GuildRepository(BaseRepository[Guild]):
    model = Guild

    async def get_by_guild_id(self, guild_id: int) -> Guild | None:
        result = await self.session.execute(select(Guild).where(Guild.guild_id == guild_id))
        return result.scalar_one_or_none()

    async def get_or_create(self, guild_id: int, *, name: str, owner_id: int) -> Guild:
        guild = await self.get_by_guild_id(guild_id)
        if guild is not None:
            if guild.name != name or guild.owner_id != owner_id or not guild.is_active:
                guild.name = name
                guild.owner_id = owner_id
                guild.is_active = True
                await self.session.flush()
            return guild

        guild = Guild(guild_id=guild_id, name=name, owner_id=owner_id, is_active=True)
        return await self.add(guild)

    async def mark_inactive(self, guild_id: int) -> None:
        guild = await self.get_by_guild_id(guild_id)
        if guild is not None:
            guild.is_active = False
            await self.session.flush()
