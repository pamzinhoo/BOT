"""Discord waits must release database sessions and preserve event-loop responsiveness."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import discord
from sqlalchemy import MetaData, delete, update

from database.models.base import Base
from database.models.guild_settings import GuildSettings
from database.models.permission_settings import PermissionSettings
from database.models.redemption import Redemption
from database.models.verification_settings import VerificationSettings
from services.redemption_service import RedemptionError, RedemptionService
from tests.test_redemption_delivery import Guild, role_code, service_for
from tests.test_redemption_postgres import redemption_db as _redemption_db

redemption_db = _redemption_db


async def test_slow_discord_delivery_holds_no_database_session(redemption_db, monkeypatch):
    active_session = ContextVar("redemption_test_active_session", default=False)
    original_session = redemption_db.session

    @asynccontextmanager
    async def traced_session():
        async with original_session() as session:
            token = active_session.set(True)
            try:
                yield session
            finally:
                active_session.reset(token)

    monkeypatch.setattr(redemption_db, "session", traced_session)
    guild = Guild()
    member = guild.member()
    service = service_for(redemption_db, guild)
    await role_code(service)
    entered = asyncio.Event()
    release = asyncio.Event()
    original_add = member.add_roles.side_effect

    async def slow_add(role, *, reason):
        assert not active_session.get(), "Discord request held a database session open"
        entered.set()
        await release.wait()
        await original_add(role, reason=reason)

    member.add_roles.side_effect = slow_add
    task = asyncio.create_task(service.redeem(guild, member, "TEMP1234"))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        # A separate operation remains available while the reward waits on Discord.
        listed = await asyncio.wait_for(service.list_codes(guild.id), timeout=2)
        assert listed[0]["uses"] == 1
        assert not task.done()
        release.set()
        result = await asyncio.wait_for(task, timeout=5)
        assert result["status"] == "delivered"
        assert guild.add_count == 1
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_concurrent_edits_reject_stale_snapshot(redemption_db, monkeypatch):
    service = RedemptionService(redemption_db)
    item = await service.create_code(1, code="TEST1234", message="Original", max_uses=20)
    gate = asyncio.Event()
    arrived = 0

    async def synchronize_validation(guild_id, data):
        nonlocal arrived
        arrived += 1
        if arrived == 2:
            gate.set()
        await gate.wait()

    monkeypatch.setattr(service, "_validate_config_role", synchronize_validation)
    outcomes = await asyncio.wait_for(
        asyncio.gather(
            service.update_code(1, uuid.UUID(item["id"]), message="Edited"),
            service.update_code(1, uuid.UUID(item["id"]), max_uses=30),
            return_exceptions=True,
        ),
        timeout=5,
    )
    assert sum(isinstance(value, dict) for value in outcomes) == 1
    assert sum(isinstance(value, RedemptionError) for value in outcomes) == 1
    final = (await service.list_codes(1))[0]
    assert (final["message"], final["max_uses"]) in {("Edited", 20), ("Original", 30)}


async def test_shared_role_scan_uses_real_settings_and_server_isolation(redemption_db):
    # Real metadata catches PostgreSQL JSONB/operator/type errors hidden by mocks.
    schema = MetaData()
    for table in Base.metadata.tables.values():
        copied = table.to_metadata(schema)
        # Legacy metadata has duplicate index names. This test needs tables and
        # column types only; retain production metadata and migration indexes.
        copied.indexes.clear()
    async with redemption_db.engine.begin() as connection:
        await connection.run_sync(schema.create_all)
    service = RedemptionService(redemption_db)
    assert not await service._shared_role(1, 55)
    for model, fields in (
        (GuildSettings, {"owner_role_id": 55}),
        (VerificationSettings, {"verified_role_id": 55}),
        (PermissionSettings, {"config": [55]}),
    ):
        async with redemption_db.session() as session:
            session.add(model(guild_id=1, **fields))
        assert await service._shared_role(1, 55)
        assert not await service._shared_role(2, 55)
        async with redemption_db.session() as session:
            await session.execute(delete(model).where(model.guild_id == 1))
        assert not await service._shared_role(1, 55)


async def test_timeout_after_success_recovers_without_duplicate_grant(redemption_db):
    from tests.test_redemption_delivery import get_rows, make_due

    guild = Guild()
    member = guild.member()
    service = service_for(redemption_db, guild)
    await role_code(service)
    row = await service._reserve(1, member.id, "TEMP1234")
    original_add = member.add_roles.side_effect

    async def uncertain_add(role, *, reason):
        await original_add(role, reason=reason)
        raise TimeoutError("Discord response lost after successful grant")

    member.add_roles.side_effect = uncertain_add
    await service._deliver(guild, row.id)
    assert guild.add_count == 1
    assert (await get_rows(redemption_db))[0][0].status == "pending"
    await make_due(redemption_db, row.id)
    restarted = service_for(redemption_db, guild)
    await restarted.process_pending()
    assert guild.add_count == 1
    assert (await get_rows(redemption_db))[0][0].status == "delivered"


async def test_restart_recovers_unsent_dm_once_and_forbidden_allows_private_pickup(redemption_db):
    from tests.test_redemption_delivery import get_rows

    guild = Guild()
    member = guild.member()
    member.send = AsyncMock()
    service = service_for(redemption_db, guild)
    await service.create_code(1, code="TEXT1234", message="Private reward", delivery="dm")
    result = await service.redeem(guild, member, "TEXT1234")
    redemption_id = uuid.UUID(result["id"])
    async with redemption_db.session() as session:
        await session.execute(
            update(Redemption)
            .where(Redemption.id == redemption_id)
            .values(updated_at=datetime.now(UTC) - timedelta(minutes=5))
        )
    await service.process_pending()
    await service.process_pending()
    member.send.assert_awaited_once()
    assert (await get_rows(redemption_db))[0][0].notification_status == "sent"

    other = guild.member(456)
    other.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "DM blocked"))
    result = await service.redeem(guild, other, "TEXT1234")
    other_id = uuid.UUID(result["id"])
    await service._recover_dm_notification(guild, other_id)
    repeated = await service.redeem(guild, other, "TEXT1234")
    assert repeated["delivery"] == "channel"
    assert repeated["notification_status"] == "pending"
    assert await service.claim_notification(guild.id, other_id)
    assert not await service.claim_notification(guild.id, other_id)


async def test_uncertain_recovered_dm_is_never_resent(redemption_db):
    guild = Guild()
    member = guild.member()
    member.send = AsyncMock(side_effect=TimeoutError("DM result unknown"))
    service = service_for(redemption_db, guild)
    await service.create_code(1, code="TEXT1234", message="Private reward", delivery="dm")
    result = await service.redeem(guild, member, "TEXT1234")
    redemption_id = uuid.UUID(result["id"])
    await service._recover_dm_notification(guild, redemption_id)
    await service._recover_dm_notification(guild, redemption_id)
    member.send.assert_awaited_once()
    repeated = await service.redeem(guild, member, "TEXT1234")
    assert repeated["notification_status"] == "uncertain"


async def test_create_updates_existing_shop_and_refresh_failure_keeps_code(redemption_db):
    from types import SimpleNamespace

    guild = Guild()
    service = service_for(redemption_db, guild)
    refresh = AsyncMock(side_effect=[None, RuntimeError("Discord offline")])
    service._bot.painel_service = SimpleNamespace(refresh_shop_panel=refresh)
    first = await service.create_code(1, code="TEXT1234", message="Private reward")
    second = await service.create_code(1, code="NEXT1234", message="Private reward")
    assert first["id"] != second["id"]
    assert refresh.await_count == 2
    assert len(await service.list_codes(1)) == 2
