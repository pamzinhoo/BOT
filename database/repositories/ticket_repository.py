from __future__ import annotations

import uuid

from sqlalchemy import func, select

from database.models.ticket import Ticket, TicketCategory, TicketStatus
from database.repositories.base_repository import BaseRepository


class TicketRepository(BaseRepository[Ticket]):
    model = Ticket

    async def get_by_channel_id(self, channel_id: int) -> Ticket | None:
        result = await self.session.execute(
            select(Ticket).where(Ticket.channel_id == channel_id)
        )
        return result.scalar_one_or_none()

    async def get_by_channel_id_locked(self, channel_id: int) -> Ticket | None:
        """Mesmo que get_by_channel_id, mas com SELECT ... FOR UPDATE — trava a
        linha ate o fim da transacao, pra que dois cliques simultaneos em
        "Assumir" nao consigam ambos passar da checagem de claim livre."""
        result = await self.session.execute(
            select(Ticket).where(Ticket.channel_id == channel_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def count_open_by_member(self, guild_id: int, member_id: int) -> int:
        result = await self.session.execute(
            select(func.count(Ticket.id)).where(
                Ticket.guild_id == guild_id,
                Ticket.opened_by_discord_id == member_id,
                Ticket.status.in_([TicketStatus.OPEN, TicketStatus.CLAIMED]),
            )
        )
        return result.scalar_one()

    async def list_open_by_guild(self, guild_id: int) -> list[Ticket]:
        result = await self.session.execute(
            select(Ticket).where(
                Ticket.guild_id == guild_id,
                Ticket.status.in_([TicketStatus.OPEN, TicketStatus.CLAIMED]),
            )
        )
        return list(result.scalars().all())

    async def list_awaiting_first_response(self, guild_id: int) -> list[Ticket]:
        result = await self.session.execute(
            select(Ticket).where(
                Ticket.guild_id == guild_id,
                Ticket.status.in_([TicketStatus.OPEN, TicketStatus.CLAIMED]),
                Ticket.first_response_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def most_common_category_for_staff(self, staff_id: uuid.UUID) -> TicketCategory | None:
        result = await self.session.execute(
            select(Ticket.category)
            .where(
                Ticket.claimed_by_staff_id == staff_id,
                Ticket.status == TicketStatus.CLOSED,
                Ticket.counts_for_stats.is_(True),
            )
            .group_by(Ticket.category)
            .order_by(func.count(Ticket.id).desc())
            .limit(1)
        )
        row = result.first()
        return row[0] if row else None

    async def list_by_staff(self, staff_id: uuid.UUID, limit: int = 10) -> list[Ticket]:
        result = await self.session.execute(
            select(Ticket)
            .where(Ticket.claimed_by_staff_id == staff_id)
            .order_by(Ticket.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
