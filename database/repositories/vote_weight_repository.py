from __future__ import annotations

import uuid

from sqlalchemy import select

from database.models.poll import VoteWeight
from database.repositories.base_repository import BaseRepository


class VoteWeightRepository(BaseRepository[VoteWeight]):
    model = VoteWeight

    async def list_by_guild(self, guild_id: int) -> list[VoteWeight]:
        result = await self.session.execute(
            select(VoteWeight).where(VoteWeight.guild_id == guild_id).order_by(VoteWeight.weight.desc())
        )
        return list(result.scalars().all())

    async def get_by_guild_and_role(self, guild_id: int, role_id: int) -> VoteWeight | None:
        result = await self.session.execute(
            select(VoteWeight).where(VoteWeight.guild_id == guild_id, VoteWeight.role_id == role_id)
        )
        return result.scalar_one_or_none()

    async def list_by_source_plan(self, plan_id: uuid.UUID) -> list[VoteWeight]:
        result = await self.session.execute(
            select(VoteWeight).where(VoteWeight.source_plan_id == plan_id)
        )
        return list(result.scalars().all())
