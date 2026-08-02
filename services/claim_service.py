from __future__ import annotations

import uuid
from datetime import UTC, datetime

from database.database import Database
from database.models.claim import Claim
from database.models.staff_activity import StaffActivityEvent
from database.models.ticket import TicketStatus
from database.repositories.claim_repository import ClaimRepository
from database.repositories.staff_activity_repository import StaffActivityRepository
from database.repositories.staff_stats_repository import StaffStatsRepository
from database.repositories.ticket_repository import TicketRepository


class ClaimError(ValueError):
    """Erro de regra de negocio ao reivindicar/liberar um ticket."""


class ClaimService:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def claim_ticket(self, channel_id: int, staff_id: uuid.UUID) -> Claim:
        now = datetime.now(UTC)
        async with self._database.session() as session:
            ticket_repo = TicketRepository(session)
            ticket = await ticket_repo.get_by_channel_id_locked(channel_id)
            if ticket is None:
                raise ClaimError("Ticket nao encontrado para este canal.")
            if ticket.status not in (TicketStatus.OPEN, TicketStatus.CLAIMED):
                raise ClaimError("Este ticket nao pode ser reivindicado no status atual.")
            if ticket.claimed_by_staff_id is not None and ticket.claimed_by_staff_id != staff_id:
                raise ClaimError("Este ticket ja esta em atendimento por outro membro da staff.")

            claim_repo = ClaimRepository(session)
            first_claim = not await claim_repo.has_prior_claim(ticket.id, staff_id)
            claim = await claim_repo.add(
                Claim(ticket_id=ticket.id, staff_id=staff_id, claimed_at=now)
            )

            ticket.status = TicketStatus.CLAIMED
            ticket.claimed_by_staff_id = staff_id

            stats = await StaffStatsRepository(session).get_or_create(staff_id)
            if first_claim:
                stats.tickets_assumidos += 1
                if stats.primeiro_ticket_at is None:
                    stats.primeiro_ticket_at = now
            stats.ticket_atual_id = ticket.id

            await StaffActivityRepository(session).log_event(
                staff_id, StaffActivityEvent.CLAIM, now
            )
            return claim

    async def unclaim_ticket(self, channel_id: int, staff_id: uuid.UUID) -> None:
        now = datetime.now(UTC)
        async with self._database.session() as session:
            ticket_repo = TicketRepository(session)
            ticket = await ticket_repo.get_by_channel_id(channel_id)
            if ticket is None or ticket.claimed_by_staff_id != staff_id:
                raise ClaimError("Voce nao esta atendendo este ticket.")

            claim_repo = ClaimRepository(session)
            active_claim = await claim_repo.get_active_claim(ticket.id)
            if active_claim is not None:
                active_claim.unclaimed_at = now

            ticket.status = TicketStatus.OPEN
            ticket.claimed_by_staff_id = None

            stats = await StaffStatsRepository(session).get_or_create(staff_id)
            if stats.ticket_atual_id == ticket.id:
                stats.ticket_atual_id = None

            await StaffActivityRepository(session).log_event(
                staff_id, StaffActivityEvent.UNCLAIM, now
            )
