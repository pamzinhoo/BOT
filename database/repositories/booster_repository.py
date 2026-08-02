from __future__ import annotations

from sqlalchemy import select

from database.models.booster import Booster
from database.repositories.base_repository import BaseRepository


class BoosterRepository(BaseRepository[Booster]):
    model = Booster

    async def get_by_guild_user(self, guild_id: int, user_id: int) -> Booster | None:
        result = await self.session.execute(
            select(Booster).where(Booster.guild_id == guild_id, Booster.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_by_guild(self, guild_id: int, limit: int = 100) -> list[Booster]:
        """Boosters de uma guild, atuais primeiro e por maior boost_count — base pro
        futuro Hall dos Boosters/ranking."""
        result = await self.session.execute(
            select(Booster)
            .where(Booster.guild_id == guild_id)
            .order_by(Booster.currently_boosting.desc(), Booster.boost_count.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
