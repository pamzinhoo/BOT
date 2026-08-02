from __future__ import annotations

import discord

from core.logger import get_logger
from database.database import Database
from database.models.guild import Guild
from database.repositories.guild_repository import GuildRepository

logger = get_logger("guild_service")


class GuildService:
    """Mantem o registro de tenants (`guilds`) em dia. Populado de forma lazy —
    nunca por backfill das tabelas antigas, que nao tem nome/dono guardados."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def ensure_guild(self, guild: discord.Guild) -> Guild:
        async with self._database.session() as session:
            repo = GuildRepository(session)
            record = await repo.get_or_create(guild.id, name=guild.name, owner_id=guild.owner_id or 0)
            await session.refresh(record)
            return record

    async def mark_inactive(self, guild_id: int) -> None:
        async with self._database.session() as session:
            await GuildRepository(session).mark_inactive(guild_id)
