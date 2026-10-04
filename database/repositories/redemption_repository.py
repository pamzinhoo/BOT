from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.redemption import Redemption, RedemptionCode, RedemptionRoleGrant


class RedemptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def code(
        self,
        guild_id: int,
        *,
        code: str | None = None,
        code_id: uuid.UUID | None = None,
        lock: bool = False,
    ) -> RedemptionCode | None:
        stmt = select(RedemptionCode).where(RedemptionCode.guild_id == guild_id)
        stmt = (
            stmt.where(RedemptionCode.code == code)
            if code is not None
            else stmt.where(RedemptionCode.id == code_id)
        )
        if lock:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def uses(self, guild_id: int, code_id: uuid.UUID) -> int:
        return int(
            (
                await self.session.execute(
                    select(func.count())
                    .select_from(Redemption)
                    .where(
                        Redemption.guild_id == guild_id,
                        Redemption.code_id == code_id,
                        Redemption.status != "failed",
                    )
                )
            ).scalar_one()
        )

    async def user_redemption(
        self, guild_id: int, code_id: uuid.UUID, user_id: int
    ) -> Redemption | None:
        return (
            await self.session.execute(
                select(Redemption).where(
                    Redemption.guild_id == guild_id,
                    Redemption.code_id == code_id,
                    Redemption.user_id == user_id,
                )
            )
        ).scalar_one_or_none()

    async def redemption(
        self, guild_id: int, redemption_id: uuid.UUID, *, lock: bool = False
    ) -> Redemption | None:
        stmt = select(Redemption).where(
            Redemption.guild_id == guild_id, Redemption.id == redemption_id
        )
        if lock:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def member_grant(self, guild_id: int, user_id: int, role_id: int) -> RedemptionRoleGrant:
        # PostgreSQL unique key serializes different codes granting the same member role.
        await self.session.execute(
            insert(RedemptionRoleGrant)
            .values(
                guild_id=guild_id,
                user_id=user_id,
                role_id=role_id,
            )
            .on_conflict_do_nothing(constraint="uq_redemption_member_role")
        )
        return (
            await self.session.execute(
                select(RedemptionRoleGrant)
                .where(
                    RedemptionRoleGrant.guild_id == guild_id,
                    RedemptionRoleGrant.user_id == user_id,
                    RedemptionRoleGrant.role_id == role_id,
                )
                .with_for_update()
            )
        ).scalar_one()

    async def grant(
        self, guild_id: int, grant_id: uuid.UUID, *, lock: bool = False
    ) -> RedemptionRoleGrant | None:
        stmt = select(RedemptionRoleGrant).where(
            RedemptionRoleGrant.guild_id == guild_id, RedemptionRoleGrant.id == grant_id
        )
        if lock:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def due(
        self, now: datetime, *, limit: int = 25, guild_ids: list[int] | None = None
    ) -> list[tuple[int, uuid.UUID]]:
        return list(
            (
                await self.session.execute(
                    select(Redemption.guild_id, Redemption.id)
                    .where(
                        Redemption.status == "pending",
                        Redemption.next_attempt_at <= now,
                        Redemption.guild_id.in_(guild_ids) if guild_ids is not None else True,
                    )
                    .order_by(Redemption.next_attempt_at)
                    .limit(limit)
                )
            ).all()
        )
