from __future__ import annotations

import uuid

from sqlalchemy import select

from database.models.evaluation import Evaluation
from database.repositories.base_repository import BaseRepository


class EvaluationRepository(BaseRepository[Evaluation]):
    model = Evaluation

    async def get_by_ticket(self, ticket_id: uuid.UUID) -> Evaluation | None:
        result = await self.session.execute(
            select(Evaluation).where(Evaluation.ticket_id == ticket_id)
        )
        return result.scalar_one_or_none()

    async def exists_for_ticket(self, ticket_id: uuid.UUID) -> bool:
        return await self.get_by_ticket(ticket_id) is not None
