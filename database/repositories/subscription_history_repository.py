from __future__ import annotations

import uuid

from sqlalchemy import select

from database.models.subscription_history import SubscriptionHistory
from database.repositories.base_repository import BaseRepository


class SubscriptionHistoryRepository(BaseRepository[SubscriptionHistory]):
    model = SubscriptionHistory

    async def list_by_subscription(self, subscription_id: uuid.UUID) -> list[SubscriptionHistory]:
        result = await self.session.execute(
            select(SubscriptionHistory)
            .where(SubscriptionHistory.subscription_id == subscription_id)
            .order_by(SubscriptionHistory.occurred_at.asc())
        )
        return list(result.scalars().all())
