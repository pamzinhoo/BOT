from __future__ import annotations

import uuid

from sqlalchemy import select

from database.models.claim import Claim
from database.repositories.base_repository import BaseRepository


class ClaimRepository(BaseRepository[Claim]):
    model = Claim

    async def get_active_claim(self, ticket_id: uuid.UUID) -> Claim | None:
        result = await self.session.execute(
            select(Claim).where(Claim.ticket_id == ticket_id, Claim.unclaimed_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def has_prior_claim(self, ticket_id: uuid.UUID, staff_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            select(Claim.id).where(Claim.ticket_id == ticket_id, Claim.staff_id == staff_id)
        )
        return result.first() is not None

    async def list_by_staff(self, staff_id: uuid.UUID) -> list[Claim]:
        result = await self.session.execute(
            select(Claim).where(Claim.staff_id == staff_id).order_by(Claim.claimed_at.desc())
        )
        return list(result.scalars().all())
