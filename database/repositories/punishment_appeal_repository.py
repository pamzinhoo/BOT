from __future__ import annotations

import uuid

from sqlalchemy import select

from database.models.punishment_appeal import AppealStatus, PunishmentAppeal
from database.repositories.base_repository import BaseRepository


class PunishmentAppealRepository(BaseRepository[PunishmentAppeal]):
    model = PunishmentAppeal

    async def list_by_punishment(self, punishment_id: uuid.UUID) -> list[PunishmentAppeal]:
        result = await self.session.execute(
            select(PunishmentAppeal)
            .where(PunishmentAppeal.punishment_id == punishment_id)
            .order_by(PunishmentAppeal.created_at.desc())
        )
        return list(result.scalars().all())

    async def has_appeal(self, punishment_id: uuid.UUID) -> bool:
        """True se ja existe qualquer recurso (pendente, aceito ou negado) pra essa punicao —
        usuario so pode enviar 1 recurso por punicao, e nao pode reenviar apos negado."""
        result = await self.session.execute(
            select(PunishmentAppeal.id).where(PunishmentAppeal.punishment_id == punishment_id)
        )
        return result.scalar_one_or_none() is not None

    async def get_pending_by_punishment(self, punishment_id: uuid.UUID) -> PunishmentAppeal | None:
        result = await self.session.execute(
            select(PunishmentAppeal).where(
                PunishmentAppeal.punishment_id == punishment_id,
                PunishmentAppeal.status == AppealStatus.PENDING,
            )
        )
        return result.scalar_one_or_none()
