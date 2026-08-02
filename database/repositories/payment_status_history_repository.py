from __future__ import annotations

import uuid

from sqlalchemy import select

from database.models.payment_status_history import PaymentStatusHistory
from database.repositories.base_repository import BaseRepository


class PaymentStatusHistoryRepository(BaseRepository[PaymentStatusHistory]):
    model = PaymentStatusHistory

    async def list_by_payment(self, payment_id: uuid.UUID) -> list[PaymentStatusHistory]:
        result = await self.session.execute(
            select(PaymentStatusHistory)
            .where(PaymentStatusHistory.payment_id == payment_id)
            .order_by(PaymentStatusHistory.created_at.asc())
        )
        return list(result.scalars().all())
