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

    async def get_by_guild_user_locked(self, guild_id: int, user_id: int) -> Booster | None:
        """Mesmo que get_by_guild_user, mas com SELECT ... FOR UPDATE — evita
        que dois disparos quase simultaneos de on_member_update (Discord as
        vezes reenvia estado em RESUME do gateway) processem o mesmo boost
        duas vezes (DM/log duplicados, boost_count incrementado 2x)."""
        result = await self.session.execute(
            select(Booster)
            .where(Booster.guild_id == guild_id, Booster.user_id == user_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_active_by_guild(self, guild_id: int) -> list[Booster]:
        """So os marcados como boosting no momento — usado pela reconciliacao
        periodica que compara contra guild.premium_subscribers."""
        result = await self.session.execute(
            select(Booster).where(
                Booster.guild_id == guild_id, Booster.currently_boosting.is_(True)
            )
        )
        return list(result.scalars().all())

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
