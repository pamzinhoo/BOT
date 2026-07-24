from __future__ import annotations

import uuid

from sqlalchemy import select

from database.models.ticket_message import TicketMessage, TicketMessageKind
from database.repositories.base_repository import BaseRepository


class TicketMessageRepository(BaseRepository[TicketMessage]):
    model = TicketMessage

    async def get(self, ticket_id: uuid.UUID, kind: TicketMessageKind) -> TicketMessage | None:
        result = await self.session.execute(
            select(TicketMessage).where(
                TicketMessage.ticket_id == ticket_id, TicketMessage.kind == kind
            )
        )
        return result.scalar_one_or_none()

    async def exists(self, ticket_id: uuid.UUID, kind: TicketMessageKind) -> bool:
        return await self.get(ticket_id, kind) is not None
