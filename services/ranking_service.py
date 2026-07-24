from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from database.database import Database
from database.models.claim import Claim
from database.models.evaluation import Evaluation
from database.models.staff import Staff
from database.repositories.staff_stats_repository import StaffStatsRepository


class RankingPeriod(enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    ALLTIME = "alltime"


@dataclass
class RankingEntry:
    staff: Staff
    tickets: int
    avaliacao_media: float


class RankingService:
    """Ranking sempre calculado on-the-fly (nunca de cache agendado).

    `alltime` le direto de staff_stats (fonte usada pelo painel ao vivo).
    Os demais periodos agregam claims/evaluations filtrando por created_at,
    sob demanda, so para o comando /ranking.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    async def compute(
        self, guild_id: int, period: RankingPeriod = RankingPeriod.ALLTIME
    ) -> list[RankingEntry]:
        if period == RankingPeriod.ALLTIME:
            return await self._alltime(guild_id)
        return await self._windowed(guild_id, period)

    async def _alltime(self, guild_id: int) -> list[RankingEntry]:
        async with self._database.session() as session:
            rows = await StaffStatsRepository(session).list_ranking_by_guild(guild_id)
            return [
                RankingEntry(
                    staff=staff,
                    tickets=stats.tickets_fechados,
                    avaliacao_media=float(stats.avaliacao_media),
                )
                for staff, stats in rows
            ]

    async def _windowed(self, guild_id: int, period: RankingPeriod) -> list[RankingEntry]:
        since = _period_start(period)
        async with self._database.session() as session:
            claim_counts = await session.execute(
                select(Claim.staff_id, func.count(Claim.id))
                .join(Staff, Staff.id == Claim.staff_id)
                .where(Staff.guild_id == guild_id, Claim.claimed_at >= since)
                .group_by(Claim.staff_id)
            )
            counts_by_staff = {row[0]: row[1] for row in claim_counts.all()}

            avg_ratings = await session.execute(
                select(Evaluation.staff_id, func.avg(Evaluation.rating))
                .join(Staff, Staff.id == Evaluation.staff_id)
                .where(Staff.guild_id == guild_id, Evaluation.created_at >= since)
                .group_by(Evaluation.staff_id)
            )
            avg_by_staff = {row[0]: row[1] for row in avg_ratings.all()}

            staff_ids = set(counts_by_staff) | set(avg_by_staff)
            if not staff_ids:
                return []

            result = await session.execute(select(Staff).where(Staff.id.in_(staff_ids)))
            staff_map = {s.id: s for s in result.scalars().all()}

            entries = [
                RankingEntry(
                    staff=staff_map[staff_id],
                    tickets=counts_by_staff.get(staff_id, 0),
                    avaliacao_media=float(avg_by_staff.get(staff_id) or 0),
                )
                for staff_id in staff_ids
            ]
            entries.sort(key=lambda e: (e.tickets, e.avaliacao_media), reverse=True)
            return entries


def _period_start(period: RankingPeriod) -> datetime:
    now = datetime.now(UTC)
    if period == RankingPeriod.DAILY:
        return now - timedelta(days=1)
    if period == RankingPeriod.WEEKLY:
        return now - timedelta(weeks=1)
    return now - timedelta(days=30)
