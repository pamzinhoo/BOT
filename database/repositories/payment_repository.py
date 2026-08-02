from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from database.models.payment import PaymentHistory, PaymentStatus
from database.repositories.base_repository import BaseRepository


class PaymentRepository(BaseRepository[PaymentHistory]):
    model = PaymentHistory

    async def list_pending_expired(self, *, before: datetime) -> list[PaymentHistory]:
        result = await self.session.execute(
            select(PaymentHistory).where(
                PaymentHistory.status == PaymentStatus.PENDING,
                PaymentHistory.expires_at.is_not(None),
                PaymentHistory.expires_at <= before,
            )
        )
        return list(result.scalars().all())

    async def get_by_provider_external_id(
        self, provider: str, external_id: str
    ) -> PaymentHistory | None:
        result = await self.session.execute(
            select(PaymentHistory).where(
                PaymentHistory.provider == provider, PaymentHistory.external_id == external_id
            )
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, guild_id: int, user_id: int) -> list[PaymentHistory]:
        result = await self.session.execute(
            select(PaymentHistory)
            .where(PaymentHistory.guild_id == guild_id, PaymentHistory.user_id == user_id)
            .order_by(PaymentHistory.created_at.desc())
        )
        return list(result.scalars().all())
