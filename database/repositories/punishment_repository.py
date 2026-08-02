from __future__ import annotations

from sqlalchemy import func, select

from database.models.punishment import (
    UNRESOLVED_STATUSES,
    Punishment,
    PunishmentStatus,
    PunishmentType,
)
from database.repositories.base_repository import BaseRepository


class PunishmentRepository(BaseRepository[Punishment]):
    model = Punishment

    async def get_by_code(self, guild_id: int, code: str) -> Punishment | None:
        result = await self.session.execute(
            select(Punishment).where(
                Punishment.guild_id == guild_id, Punishment.punishment_code == code
            )
        )
        return result.scalar_one_or_none()

    async def get_by_code_global(self, code: str) -> Punishment | None:
        """Busca por punishment_code sem filtrar guild — usado no fallback de recurso por
        DM, onde nao ha contexto de guild disponivel. punishment_code e unique globalmente."""
        result = await self.session.execute(
            select(Punishment).where(Punishment.punishment_code == code)
        )
        return result.scalar_one_or_none()

    async def code_exists(self, code: str) -> bool:
        result = await self.session.execute(
            select(Punishment.id).where(Punishment.punishment_code == code)
        )
        return result.scalar_one_or_none() is not None

    async def list_by_user(self, guild_id: int, user_id: int, limit: int = 50) -> list[Punishment]:
        result = await self.session.execute(
            select(Punishment)
            .where(Punishment.guild_id == guild_id, Punishment.user_id == user_id)
            .order_by(Punishment.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def has_revoked_punishment(self, guild_id: int, user_id: int) -> bool:
        """True se o usuario tem qualquer punicao revogada nesta guild — usado pra
        devolver o cargo de jogador quando ele reentra (ban/ban_temporario/kick tiram
        o membro da guild; so da pra restaurar cargo no rejoin)."""
        result = await self.session.execute(
            select(Punishment.id).where(
                Punishment.guild_id == guild_id,
                Punishment.user_id == user_id,
                Punishment.status == PunishmentStatus.REVOKED,
            )
        )
        return result.scalar_one_or_none() is not None

    async def get_last_by_user(self, guild_id: int, user_id: int) -> Punishment | None:
        result = await self.session.execute(
            select(Punishment)
            .where(Punishment.guild_id == guild_id, Punishment.user_id == user_id)
            .order_by(Punishment.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def count_by_type(self, guild_id: int, user_id: int, ptype: PunishmentType) -> int:
        result = await self.session.execute(
            select(func.count(Punishment.id)).where(
                Punishment.guild_id == guild_id,
                Punishment.user_id == user_id,
                Punishment.type == ptype,
            )
        )
        return result.scalar_one()

    async def has_open_punishment_of_type(self, guild_id: int, user_id: int, ptype: PunishmentType) -> bool:
        """True se ja existe punicao ACTIVE ou ainda nao resolvida (PENDING/NOTIFIED) do
        mesmo tipo pra esse usuario — usado no anti-duplicacao (Etapa 3)."""
        statuses = {PunishmentStatus.ACTIVE, PunishmentStatus.PENDING_REVIEW, *UNRESOLVED_STATUSES}
        result = await self.session.execute(
            select(Punishment.id).where(
                Punishment.guild_id == guild_id,
                Punishment.user_id == user_id,
                Punishment.type == ptype,
                Punishment.status.in_(statuses),
            )
        )
        return result.scalar_one_or_none() is not None

    async def list_expired_pending_reviews(self, now) -> list[Punishment]:
        """Punicoes em analise (Etapa 22) cujo prazo de recurso ja passou — usadas pelo
        ReviewExpirationTask pra aplicar a punicao real automaticamente."""
        result = await self.session.execute(
            select(Punishment).where(
                Punishment.status == PunishmentStatus.PENDING_REVIEW,
                Punishment.review_deadline_at.is_not(None),
                Punishment.review_deadline_at <= now,
            )
        )
        return list(result.scalars().all())

    async def list_pending_review(
        self,
        guild_id: int,
        *,
        types: set[PunishmentType] | None = None,
        staff_id: int | None = None,
    ) -> list[Punishment]:
        """Punições atualmente em análise (isoladas, aguardando recurso ou expiração) pra
        uso no painel /analises. Mais antigas primeiro (quem espera há mais tempo aparece no topo)."""
        query = select(Punishment).where(
            Punishment.guild_id == guild_id,
            Punishment.status == PunishmentStatus.PENDING_REVIEW,
        )
        if types:
            query = query.where(Punishment.type.in_(types))
        if staff_id is not None:
            query = query.where(Punishment.staff_id == staff_id)
        result = await self.session.execute(query.order_by(Punishment.created_at.asc()))
        return list(result.scalars().all())

    async def list_expired_active_temp_bans(self, now) -> list[Punishment]:
        """Punicoes temporarias ainda ACTIVE cujo expires_at ja passou (sweep de unban)."""
        result = await self.session.execute(
            select(Punishment).where(
                Punishment.status == PunishmentStatus.ACTIVE,
                Punishment.expires_at.is_not(None),
                Punishment.expires_at <= now,
            )
        )
        return list(result.scalars().all())
