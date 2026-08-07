from __future__ import annotations

import uuid

from sqlalchemy import select

from database.models.plan import Plan
from database.models.plan_benefit import PlanBenefit
from database.models.plan_message import PlanMessage
from database.repositories.base_repository import BaseRepository


class PlanRepository(BaseRepository[Plan]):
    model = Plan

    async def get_by_id(self, id_: uuid.UUID) -> Plan | None:
        return await self.session.get(Plan, id_)

    async def get_by_guild_and_name(self, guild_id: int, name: str) -> Plan | None:
        result = await self.session.execute(
            select(Plan).where(Plan.guild_id == guild_id, Plan.name == name)
        )
        return result.scalar_one_or_none()

    async def list_by_guild(self, guild_id: int, *, only_active: bool = False) -> list[Plan]:
        stmt = select(Plan).where(Plan.guild_id == guild_id)
        if only_active:
            stmt = stmt.where(Plan.is_active.is_(True))
        stmt = stmt.order_by(Plan.position.asc(), Plan.created_at.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_product(self, product_id: uuid.UUID) -> list[Plan]:
        """Cross-guild de proposito (unico lugar do repo que quebra a
        convencao list_by_guild) — RoleSyncService/ReconciliationService
        precisam encontrar, pra um Product, TODOS os planos de TODAS as
        guilds que concedem cargo por ele, pra refletir License->cargo em
        cada servidor. Nao serve pra UI (nao lista dado de uma guild pra
        outra), so pra sincronizacao interna backend->Discord."""
        result = await self.session.execute(
            select(Plan).where(Plan.product_id == product_id, Plan.role_id.is_not(None))
        )
        return list(result.scalars().all())


class PlanBenefitRepository(BaseRepository[PlanBenefit]):
    model = PlanBenefit

    async def list_by_plan(self, plan_id: uuid.UUID) -> list[PlanBenefit]:
        result = await self.session.execute(
            select(PlanBenefit)
            .where(PlanBenefit.plan_id == plan_id)
            .order_by(PlanBenefit.position.asc())
        )
        return list(result.scalars().all())

    async def delete_all_for_plan(self, plan_id: uuid.UUID) -> None:
        benefits = await self.list_by_plan(plan_id)
        for benefit in benefits:
            await self.session.delete(benefit)
        await self.session.flush()


class PlanMessageRepository(BaseRepository[PlanMessage]):
    model = PlanMessage

    async def list_by_plan(self, plan_id: uuid.UUID) -> list[PlanMessage]:
        result = await self.session.execute(
            select(PlanMessage).where(PlanMessage.plan_id == plan_id)
        )
        return list(result.scalars().all())

    async def get_by_plan_and_type(self, plan_id: uuid.UUID, message_type: object) -> PlanMessage | None:
        result = await self.session.execute(
            select(PlanMessage).where(
                PlanMessage.plan_id == plan_id, PlanMessage.message_type == message_type
            )
        )
        return result.scalar_one_or_none()
