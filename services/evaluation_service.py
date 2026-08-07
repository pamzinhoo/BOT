from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from database.database import Database
from database.models.evaluation import Evaluation
from database.models.ticket import Ticket
from database.repositories.achievement_repository import AchievementRepository
from database.repositories.evaluation_repository import EvaluationRepository
from database.repositories.staff_stats_repository import StaffStatsRepository
from database.repositories.ticket_repository import TicketRepository
from utils.formatter import running_average

_BAD_RATING_THRESHOLD = 2
_CLEAN_STREAK_DAYS = 30


class EvaluationError(ValueError):
    """Erro de regra de negocio ao registrar uma avaliacao."""


@dataclass
class EvaluationResult:
    evaluation: Evaluation
    unlocked_achievements: list[str] = field(default_factory=list)


class EvaluationService:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def has_evaluation(self, ticket_id: uuid.UUID) -> bool:
        async with self._database.session() as session:
            return await EvaluationRepository(session).exists_for_ticket(ticket_id)

    async def submit_evaluation(
        self, channel_id: int, rated_by_discord_id: int, rating: int, comment: str | None
    ) -> EvaluationResult:
        async with self._database.session() as session:
            ticket = await TicketRepository(session).get_by_channel_id(channel_id)
            if ticket is None:
                raise EvaluationError("Ticket nao encontrado para este canal.")
            return await self._apply_evaluation(session, ticket, rated_by_discord_id, rating, comment)

    async def submit_evaluation_by_ticket_id(
        self, ticket_id: uuid.UUID, rated_by_discord_id: int, rating: int, comment: str | None
    ) -> EvaluationResult:
        """Mesma regra de negocio de submit_evaluation, mas resolvendo o ticket
        pelo id em vez do channel_id — usado quando a avaliacao chega por DM
        (canal do ticket ja foi excluido, entao nao ha channel_id pra resolver)."""
        async with self._database.session() as session:
            ticket = await TicketRepository(session).get_by_id(ticket_id)
            if ticket is None:
                raise EvaluationError("Ticket nao encontrado.")
            return await self._apply_evaluation(session, ticket, rated_by_discord_id, rating, comment)

    async def _apply_evaluation(
        self,
        session: AsyncSession,
        ticket: Ticket,
        rated_by_discord_id: int,
        rating: int,
        comment: str | None,
    ) -> EvaluationResult:
        if not 1 <= rating <= 5:
            raise EvaluationError("A avaliacao deve ser um numero entre 1 e 5.")
        if ticket.claimed_by_staff_id is None:
            raise EvaluationError("Este ticket nao possui um staff responsavel.")
        if ticket.opened_by_discord_id != rated_by_discord_id:
            raise EvaluationError("Apenas quem abriu o ticket pode avalia-lo.")

        eval_repo = EvaluationRepository(session)
        if await eval_repo.exists_for_ticket(ticket.id):
            raise EvaluationError("Este ticket ja foi avaliado.")

        evaluation = await eval_repo.add(
            Evaluation(
                ticket_id=ticket.id,
                staff_id=ticket.claimed_by_staff_id,
                rated_by_discord_id=rated_by_discord_id,
                rating=rating,
                comment=comment,
            )
        )

        stats = await StaffStatsRepository(session).get_or_create(ticket.claimed_by_staff_id)
        old_avg = float(stats.avaliacao_media) if stats.avaliacoes_count else None
        stats.avaliacao_media = running_average(old_avg, stats.avaliacoes_count, rating)
        stats.avaliacoes_count += 1
        stats.melhor_avaliacao = (
            rating if stats.melhor_avaliacao is None else max(stats.melhor_avaliacao, rating)
        )
        stats.pior_avaliacao = (
            rating if stats.pior_avaliacao is None else min(stats.pior_avaliacao, rating)
        )

        now = datetime.now(UTC)
        achievement_repo = AchievementRepository(session)
        unlocked: list[str] = []

        if rating == 5 and await achievement_repo.award(ticket.claimed_by_staff_id, "five_star"):
            unlocked.append("five_star")

        stats.current_perfect_streak = stats.current_perfect_streak + 1 if rating == 5 else 0

        if rating <= _BAD_RATING_THRESHOLD:
            stats.last_bad_rating_at = now
        else:
            baseline = stats.last_bad_rating_at or stats.primeiro_ticket_at or now
            clean_days = (now - baseline).total_seconds() / 86400
            if clean_days >= _CLEAN_STREAK_DAYS and await achievement_repo.award(
                ticket.claimed_by_staff_id, "clean_30_days"
            ):
                unlocked.append("clean_30_days")

        return EvaluationResult(evaluation=evaluation, unlocked_achievements=unlocked)
