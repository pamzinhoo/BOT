from __future__ import annotations

import uuid

from sqlalchemy import select

from database.models.subscription import Subscription, SubscriptionStatus
from database.repositories.base_repository import BaseRepository


class SubscriptionRepository(BaseRepository[Subscription]):
    model = Subscription

    async def get_by_external_reference(self, external_reference: str) -> Subscription | None:
        result = await self.session.execute(
            select(Subscription).where(Subscription.external_reference == external_reference)
        )
        return result.scalar_one_or_none()

    async def get_by_user_plan(
        self, guild_id: int, user_id: int, plan_id: uuid.UUID
    ) -> Subscription | None:
        """Independente de status — usada pra reaproveitar a linha (unica por
        guild+user+plan, UniqueConstraint uq_subscription_guild_user_plan) numa
        recompra apos cancelamento/rejeicao/expiracao, em vez de tentar inserir
        outra e estourar a constraint."""
        result = await self.session.execute(
            select(Subscription).where(
                Subscription.guild_id == guild_id,
                Subscription.user_id == user_id,
                Subscription.plan_id == plan_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_active_for_user_plan(
        self, guild_id: int, user_id: int, plan_id: uuid.UUID
    ) -> Subscription | None:
        result = await self.session.execute(
            select(Subscription).where(
                Subscription.guild_id == guild_id,
                Subscription.user_id == user_id,
                Subscription.plan_id == plan_id,
                Subscription.status.in_([SubscriptionStatus.PENDING, SubscriptionStatus.ACTIVE]),
            )
        )
        return result.scalar_one_or_none()

    async def list_active_by_user(self, guild_id: int, user_id: int) -> list[Subscription]:
        result = await self.session.execute(
            select(Subscription).where(
                Subscription.guild_id == guild_id,
                Subscription.user_id == user_id,
                Subscription.status == SubscriptionStatus.ACTIVE,
            )
        )
        return list(result.scalars().all())

    async def list_active_or_pending_by_user(self, guild_id: int, user_id: int) -> list[Subscription]:
        result = await self.session.execute(
            select(Subscription).where(
                Subscription.guild_id == guild_id,
                Subscription.user_id == user_id,
                Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.PENDING]),
            )
        )
        return list(result.scalars().all())

    async def list_by_guild(self, guild_id: int) -> list[Subscription]:
        result = await self.session.execute(
            select(Subscription).where(Subscription.guild_id == guild_id)
        )
        return list(result.scalars().all())

    async def list_active_with_period(self, guild_id: int) -> list[Subscription]:
        """Ativas com periodo definido — base do scheduler de renovacao
        (pagamento unico nao tem current_period_end, entao fica de fora)."""
        result = await self.session.execute(
            select(Subscription).where(
                Subscription.guild_id == guild_id,
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.current_period_end.is_not(None),
            )
        )
        return list(result.scalars().all())

    async def list_expiring_active(self, *, before: object) -> list[Subscription]:
        result = await self.session.execute(
            select(Subscription).where(
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.current_period_end.is_not(None),
                Subscription.current_period_end <= before,
            )
        )
        return list(result.scalars().all())
