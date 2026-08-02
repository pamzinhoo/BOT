from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select

from database.models.poll import Poll, PollOption, PollStatus, PollVote
from database.repositories.base_repository import BaseRepository


class PollRepository(BaseRepository[Poll]):
    model = Poll

    async def list_by_guild(self, guild_id: int) -> list[Poll]:
        result = await self.session.execute(
            select(Poll).where(Poll.guild_id == guild_id).order_by(Poll.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_open_expiring(self, before: datetime) -> list[Poll]:
        result = await self.session.execute(
            select(Poll).where(Poll.status == PollStatus.OPEN, Poll.expires_at <= before)
        )
        return list(result.scalars().all())


class PollOptionRepository(BaseRepository[PollOption]):
    model = PollOption

    async def list_by_poll(self, poll_id: uuid.UUID) -> list[PollOption]:
        result = await self.session.execute(
            select(PollOption).where(PollOption.poll_id == poll_id).order_by(PollOption.position.asc())
        )
        return list(result.scalars().all())


class PollVoteRepository(BaseRepository[PollVote]):
    model = PollVote

    async def get_by_poll_and_user(self, poll_id: uuid.UUID, user_id: int) -> PollVote | None:
        result = await self.session.execute(
            select(PollVote).where(PollVote.poll_id == poll_id, PollVote.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def weighted_totals(self, poll_id: uuid.UUID) -> dict[uuid.UUID, int]:
        result = await self.session.execute(
            select(PollVote.option_id, func.sum(PollVote.weight))
            .where(PollVote.poll_id == poll_id)
            .group_by(PollVote.option_id)
        )
        return {option_id: int(total) for option_id, total in result.all()}

    async def count_participants(self, poll_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(PollVote).where(PollVote.poll_id == poll_id)
        )
        return int(result.scalar_one())

    async def list_open_live_votes_for_user(self, user_id: int) -> list[PollVote]:
        """Votos do usuario em enquetes abertas com weight_mode="LIVE" — usadas
        pelo listener de mudanca de cargo pra saber se precisa recalcular peso."""
        result = await self.session.execute(
            select(PollVote)
            .join(Poll, Poll.id == PollVote.poll_id)
            .where(
                PollVote.user_id == user_id,
                Poll.status == PollStatus.OPEN,
                Poll.weight_mode == "LIVE",
            )
        )
        return list(result.scalars().all())
