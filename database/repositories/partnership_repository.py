from __future__ import annotations

from sqlalchemy import select

from database.models.partnership import Partnership
from database.repositories.base_repository import BaseRepository


class PartnershipRepository(BaseRepository[Partnership]):
    model = Partnership

    async def get_by_guild_owner(self, guild_id: int, owner_id: int) -> Partnership | None:
        result = await self.session.execute(
            select(Partnership).where(
                Partnership.guild_id == guild_id, Partnership.owner_id == owner_id
            )
        )
        return result.scalar_one_or_none()

    async def get_by_guild_owner_locked(self, guild_id: int, owner_id: int) -> Partnership | None:
        """Mesmo que get_by_guild_owner, mas com SELECT ... FOR UPDATE — evita
        que dois /parceria publicar quase simultaneos do mesmo parceiro criem
        dois canais/topicos em paralelo (race condition)."""
        result = await self.session.execute(
            select(Partnership)
            .where(Partnership.guild_id == guild_id, Partnership.owner_id == owner_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_channel_or_thread(
        self, guild_id: int, channel_id: int
    ) -> Partnership | None:
        result = await self.session.execute(
            select(Partnership).where(
                Partnership.guild_id == guild_id,
                (Partnership.channel_id == channel_id) | (Partnership.thread_id == channel_id),
            )
        )
        return result.scalar_one_or_none()

    async def list_by_guild(self, guild_id: int) -> list[Partnership]:
        result = await self.session.execute(
            select(Partnership).where(Partnership.guild_id == guild_id)
        )
        return list(result.scalars().all())
