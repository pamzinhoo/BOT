from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from database.database import Database
from database.models.achievement import Achievement
from database.models.staff import Staff
from database.models.staff_stats import StaffStats
from database.models.ticket import Ticket, TicketCategory
from database.repositories.achievement_repository import AchievementRepository
from database.repositories.staff_repository import StaffRepository
from database.repositories.staff_stats_repository import StaffStatsRepository
from database.repositories.ticket_repository import TicketRepository
from utils.timing import timed_step
from utils.ttl_cache import TTLCache

# ensure_staff roda em TODO clique de Assumir/Liberar (views/ticket_actions_view.py,
# cogs/claim.py) so pra garantir que a linha de staff existe e o display_name
# esta em dia — na esmagadora maioria das vezes o staff ja existe e o nome nao
# mudou desde o ultimo clique. TTL curto (o nick pode mudar a qualquer
# momento, mas nao precisa refletir instantaneamente num campo so
# informativo) evita 1 SELECT + 1 COMMIT por clique quando nada mudou.
_STAFF_CACHE_TTL_SECONDS = 120.0


@dataclass
class StaffProfile:
    staff: Staff
    stats: StaffStats
    recent_tickets: list[Ticket]
    specialty: TicketCategory | None = None
    achievements: list[Achievement] = field(default_factory=list)


class StaffService:
    def __init__(self, database: Database) -> None:
        self._database = database
        self._staff_cache: TTLCache[tuple[int, int], Staff] = TTLCache(_STAFF_CACHE_TTL_SECONDS)

    async def ensure_staff(self, guild_id: int, discord_user_id: int, display_name: str) -> Staff:
        cache_key = (guild_id, discord_user_id)
        cached = self._staff_cache.get(cache_key)
        if cached is not None and cached.display_name == display_name:
            return cached
        async with timed_step("ensure_staff", "db"), self._database.session() as session:
            repo = StaffRepository(session)
            staff = await repo.get_by_discord_id(guild_id, discord_user_id)
            if staff is not None:
                if staff.display_name != display_name:
                    staff.display_name = display_name
            else:
                staff = await repo.add(
                    Staff(
                        guild_id=guild_id,
                        discord_user_id=discord_user_id,
                        display_name=display_name,
                    )
                )
                await StaffStatsRepository(session).get_or_create(staff.id)
        self._staff_cache.set(cache_key, staff)
        return staff

    async def get_by_id(self, staff_id: uuid.UUID) -> Staff | None:
        async with self._database.session() as session:
            return await StaffRepository(session).get_by_id(staff_id)

    async def get_profile(self, guild_id: int, discord_user_id: int) -> StaffProfile | None:
        async with self._database.session() as session:
            staff = await StaffRepository(session).get_by_discord_id(guild_id, discord_user_id)
            if staff is None:
                return None
            stats = await StaffStatsRepository(session).get_or_create(staff.id)
            ticket_repo = TicketRepository(session)
            tickets = await ticket_repo.list_by_staff(staff.id, limit=10)
            specialty = await ticket_repo.most_common_category_for_staff(staff.id)
            achievements = await AchievementRepository(session).list_by_staff(staff.id)
            return StaffProfile(
                staff=staff,
                stats=stats,
                recent_tickets=tickets,
                specialty=specialty,
                achievements=achievements,
            )
