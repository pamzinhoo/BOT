from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select

from database.models.giveaway import Giveaway, GiveawayEntry, GiveawayStatus, GiveawayWinner
from database.repositories.base_repository import BaseRepository


class GiveawayRepository(BaseRepository[Giveaway]):
    model = Giveaway

    async def list_by_guild(self, guild_id: int) -> list[Giveaway]:
        result = await self.session.execute(
            select(Giveaway).where(Giveaway.guild_id == guild_id).order_by(Giveaway.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_open_expiring(self, before: datetime) -> list[Giveaway]:
        result = await self.session.execute(
            select(Giveaway).where(Giveaway.status == GiveawayStatus.OPEN, Giveaway.expires_at <= before)
        )
        return list(result.scalars().all())

    async def get_by_id_locked(self, giveaway_id: uuid.UUID) -> Giveaway | None:
        """Mesmo que get_by_id, mas com SELECT ... FOR UPDATE — trava a linha
        ate o fim da transacao, pra evitar um encerramento manual e a varredura
        automatica (ou dois cliques de "sortear novamente") lerem o mesmo
        status e sortearem/entregarem o premio duas vezes."""
        result = await self.session.execute(
            select(Giveaway).where(Giveaway.id == giveaway_id).with_for_update()
        )
        return result.scalar_one_or_none()


class GiveawayEntryRepository(BaseRepository[GiveawayEntry]):
    model = GiveawayEntry

    async def get_by_giveaway_and_user(self, giveaway_id: uuid.UUID, user_id: int) -> GiveawayEntry | None:
        result = await self.session.execute(
            select(GiveawayEntry).where(
                GiveawayEntry.giveaway_id == giveaway_id, GiveawayEntry.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def list_by_giveaway(self, giveaway_id: uuid.UUID) -> list[GiveawayEntry]:
        result = await self.session.execute(
            select(GiveawayEntry).where(GiveawayEntry.giveaway_id == giveaway_id)
        )
        return list(result.scalars().all())

    async def count_by_giveaway(self, giveaway_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(GiveawayEntry).where(GiveawayEntry.giveaway_id == giveaway_id)
        )
        return int(result.scalar_one())


class GiveawayWinnerRepository(BaseRepository[GiveawayWinner]):
    model = GiveawayWinner

    async def list_by_giveaway(self, giveaway_id: uuid.UUID) -> list[GiveawayWinner]:
        result = await self.session.execute(
            select(GiveawayWinner)
            .where(GiveawayWinner.giveaway_id == giveaway_id)
            .order_by(GiveawayWinner.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_user_ids_by_giveaway(self, giveaway_id: uuid.UUID) -> list[int]:
        result = await self.session.execute(
            select(GiveawayWinner.user_id).where(GiveawayWinner.giveaway_id == giveaway_id)
        )
        return list(result.scalars().all())
