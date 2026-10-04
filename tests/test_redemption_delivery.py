"""Delivery fault injection against the isolated PostgreSQL reservation state."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, update

from database.models.redemption import Redemption, RedemptionRoleGrant
from services.redemption_service import RedemptionError, RedemptionService
from tests.test_redemption_postgres import redemption_db as _redemption_db

redemption_db = _redemption_db


class Role:
    id = 55
    managed = False
    permissions = SimpleNamespace()

    def __ge__(self, other):
        return False


class Guild:
    id = 1

    def __init__(self):
        self.role = Role()
        self.me = SimpleNamespace(
            id=777,
            top_role=object(),
            guild_permissions=SimpleNamespace(manage_roles=True, view_audit_log=True),
        )
        self.entries = []
        self.members = {}
        self.add_count = 0
        self.remove_count = 0

    def get_role(self, role_id):
        return self.role if role_id == self.role.id else None

    async def fetch_member(self, user_id):
        return self.members[user_id]

    async def audit_logs(self, **kwargs):
        for entry in reversed(self.entries):
            yield entry

    def member(self, user_id=123):
        member = SimpleNamespace(id=user_id, guild=self, roles=[], bot=False)

        async def add(role, *, reason):
            self.add_count += 1
            await asyncio.sleep(0.01)
            member.roles.append(role)
            self.entries.append(
                SimpleNamespace(
                    target=member,
                    user=self.me,
                    reason=reason,
                    before=SimpleNamespace(roles=[]),
                    after=SimpleNamespace(roles=[role]),
                )
            )

        async def remove(role, *, reason):
            self.remove_count += 1
            member.roles.remove(role)

        member.add_roles = AsyncMock(side_effect=add)
        member.remove_roles = AsyncMock(side_effect=remove)
        self.members[user_id] = member
        return member


def service_for(database, guild):
    bot = SimpleNamespace(
        guilds=[guild],
        get_guild=lambda guild_id: guild if guild_id == guild.id else None,
        audit_log_service=SimpleNamespace(record=AsyncMock()),
    )
    service = RedemptionService(database, bot)
    service._shared_role = AsyncMock(return_value=False)
    return service


async def role_code(service, code="TEMP1234", duration=60):
    return await service.create_code(
        1,
        code=code,
        reward_type="role",
        role_id=55,
        role_duration_seconds=duration,
        temporary_role_ack=duration is not None,
        message="Olá {usuario}; {cargo}; {duracao}",
        max_uses=20,
    )


async def get_rows(database):
    async with database.session() as session:
        rows = list(
            (await session.execute(select(Redemption).order_by(Redemption.created_at))).scalars()
        )
        grants = list((await session.execute(select(RedemptionRoleGrant))).scalars())
        return rows, grants


async def expire(database, grant_id):
    async with database.session() as session:
        await session.execute(
            update(RedemptionRoleGrant)
            .where(RedemptionRoleGrant.id == grant_id)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )


async def make_due(database, redemption_id):
    async with database.session() as session:
        await session.execute(
            update(Redemption)
            .where(Redemption.id == redemption_id)
            .values(next_attempt_at=datetime.now(UTC) - timedelta(seconds=1))
        )


async def test_concurrent_delivery_uses_one_lease_and_expires_owned_role(redemption_db):
    guild = Guild()
    member = guild.member()
    service = service_for(redemption_db, guild)
    await role_code(service)
    row = await service._reserve(1, member.id, "TEMP1234")
    await asyncio.gather(*(service._deliver(guild, row.id) for _ in range(10)))
    rows, grants = await get_rows(redemption_db)
    assert rows[0].status == "delivered"
    assert guild.add_count == 1
    assert grants[0].owns_role
    assert rows[0].role_expires_at > rows[0].delivered_at
    await expire(redemption_db, grants[0].id)
    await service.process_pending()
    await service.process_pending()
    assert guild.remove_count == 1
    assert member.roles == []
    assert (await get_rows(redemption_db))[1][0].status == "removed"


async def test_preexisting_role_rejected_without_consuming_code(redemption_db):
    guild = Guild()
    member = guild.member()
    member.roles = [guild.role]
    service = service_for(redemption_db, guild)
    await role_code(service)
    with pytest.raises(RedemptionError, match="já possui"):
        await service.redeem(guild, member, "TEMP1234")
    assert (await service.list_codes(1))[0]["uses"] == 0
    assert (await get_rows(redemption_db))[0] == []


async def test_restart_after_discord_success_before_commit_does_not_grant_twice(redemption_db):
    guild = Guild()
    member = guild.member()
    service = service_for(redemption_db, guild)
    await role_code(service)
    row = await service._reserve(1, member.id, "TEMP1234")
    service._finish_delivery = AsyncMock(side_effect=RuntimeError("simulated database disconnect"))
    await service._deliver(guild, row.id)
    assert guild.add_count == 1
    assert (await get_rows(redemption_db))[0][0].status == "pending"
    await make_due(redemption_db, row.id)
    restarted = service_for(redemption_db, guild)
    await restarted.process_pending()
    assert guild.add_count == 1
    rows, grants = await get_rows(redemption_db)
    assert rows[0].status == "delivered"
    assert grants[0].owns_role


async def test_external_role_regrant_prevents_expiration(redemption_db):
    guild = Guild()
    member = guild.member()
    service = service_for(redemption_db, guild)
    await role_code(service)
    await service.redeem(guild, member, "TEMP1234")
    _, grants = await get_rows(redemption_db)
    guild.entries.append(
        SimpleNamespace(
            target=member,
            user=SimpleNamespace(id=999),
            reason="manual",
            before=SimpleNamespace(roles=[]),
            after=SimpleNamespace(roles=[guild.role]),
        )
    )
    await expire(redemption_db, grants[0].id)
    await service.process_pending()
    assert guild.remove_count == 0
    assert (await get_rows(redemption_db))[1][0].status == "suspended"


async def test_overlap_and_permanent_reward_prevent_early_removal(redemption_db):
    guild = Guild()
    member = guild.member()
    service = service_for(redemption_db, guild)
    await role_code(service)
    await role_code(service, "NEXT1234", 3600)
    await role_code(service, "LIFE1234", None)
    await service.redeem(guild, member, "TEMP1234")
    await service.redeem(guild, member, "NEXT1234")
    rows, grants = await get_rows(redemption_db)
    assert grants[0].expires_at == rows[-1].role_expires_at
    assert rows[-1].role_expires_at > rows[0].role_expires_at
    await service.redeem(guild, member, "LIFE1234")
    await expire(redemption_db, grants[0].id)
    await service.process_pending()
    assert guild.add_count == 1 and guild.remove_count == 0
    assert (await get_rows(redemption_db))[1][0].permanent


async def test_second_pending_code_same_role_cannot_steal_ownership(redemption_db):
    guild = Guild()
    member = guild.member()
    service = service_for(redemption_db, guild)
    await role_code(service)
    await role_code(service, "NEXT1234")
    await service._reserve(1, member.id, "TEMP1234")
    with pytest.raises(RedemptionError, match="Outro resgate"):
        await service._reserve(1, member.id, "NEXT1234")


async def test_notification_claim_is_atomic_and_stale_send_becomes_uncertain(redemption_db):
    guild = Guild()
    member = guild.member()
    service = service_for(redemption_db, guild)
    await service.create_code(1, code="TEXT1234", message="secret")
    result = await service.redeem(guild, member, "TEXT1234")
    row_id = uuid.UUID(result["id"])
    claims = await asyncio.gather(*(service.claim_notification(1, row_id) for _ in range(20)))
    assert sum(claims) == 1
    async with redemption_db.session() as session:
        await session.execute(
            update(Redemption)
            .where(Redemption.id == row_id)
            .values(updated_at=datetime.now(UTC) - timedelta(minutes=2))
        )
    await service.process_pending()
    assert (await get_rows(redemption_db))[0][0].notification_status == "uncertain"
    assert not await service.claim_notification(1, row_id)


async def test_role_shared_after_grant_suspends_expiry(redemption_db):
    guild = Guild()
    member = guild.member()
    service = service_for(redemption_db, guild)
    await role_code(service)
    await service.redeem(guild, member, "TEMP1234")
    _, grants = await get_rows(redemption_db)
    service._shared_role.return_value = True
    await expire(redemption_db, grants[0].id)
    await service.process_pending()
    assert guild.remove_count == 0
    assert (await get_rows(redemption_db))[1][0].status == "suspended"


@pytest.mark.parametrize("duration", [None, 60])
async def test_shared_shop_role_can_be_created_and_redeemed_without_unsafe_expiry(
    redemption_db, duration
):
    guild = Guild()
    member = guild.member()
    service = service_for(redemption_db, guild)
    service._shared_role.return_value = True
    await role_code(service, duration=duration)
    result = await service.redeem(guild, member, "TEMP1234")
    assert result["status"] == "delivered"
    assert guild.add_count == 1
    delivered_log = service._bot.audit_log_service.record.await_args.kwargs
    assert delivered_log["target_id"] == member.id
    assert str(member.id) in delivered_log["target_name"]
    _, grants = await get_rows(redemption_db)
    await expire(redemption_db, grants[0].id)
    await service.process_pending()
    assert guild.remove_count == 0
    if duration:
        grant = (await get_rows(redemption_db))[1][0]
        assert grant.status == "suspended"
        assert "outro recurso" in grant.error
