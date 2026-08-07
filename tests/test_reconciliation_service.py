from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from database.models.license import License, LicenseStatus
from database.models.plan import Plan
from database.models.player import Player
from services.reconciliation_service import ReconciliationService
from tests._fakes_role_sync import (
    FakeAuditLogService,
    FakeDatabase,
    RoleSyncFakeStore,
    install_reconciliation_fakes,
)


def _player(discord_id: int) -> Player:
    player = Player(discord_id=discord_id, discord_username="tester", linked_at=datetime.now(UTC))
    player.id = uuid.uuid4()
    return player


def _license(player_id: uuid.UUID, product_id: uuid.UUID, *, status: LicenseStatus = LicenseStatus.ACTIVE) -> License:
    lic = License(player_id=player_id, product_id=product_id, status=status, purchase_source="loja")
    lic.id = uuid.uuid4()
    return lic


def _plan(*, guild_id: int, product_id: uuid.UUID, role_id: int) -> Plan:
    plan = Plan(guild_id=guild_id, name="Patrono", product_id=product_id, role_id=role_id)
    plan.id = uuid.uuid4()
    return plan


def _member(discord_id: int, *, roles: list[discord.Role]) -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.id = discord_id
    member.roles = roles
    member.add_roles = AsyncMock()
    member.remove_roles = AsyncMock()
    return member


@pytest.fixture
def store() -> RoleSyncFakeStore:
    return RoleSyncFakeStore()


@pytest.fixture
def bot(store: RoleSyncFakeStore) -> MagicMock:
    fake_bot = MagicMock()
    fake_bot.audit_log_service = FakeAuditLogService(store)
    return fake_bot


@pytest.fixture
def service(monkeypatch, store: RoleSyncFakeStore, bot: MagicMock) -> ReconciliationService:
    install_reconciliation_fakes(monkeypatch, store)
    return ReconciliationService(FakeDatabase(store), bot)


def _guild_with_role(guild_id: int, role: discord.Role, *, role_members: list[discord.Member]) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    guild.get_role.return_value = role
    role.members = role_members
    members_by_id = {m.id: m for m in role_members}
    guild.get_member.side_effect = lambda mid: members_by_id.get(mid)
    return guild


async def test_removes_role_when_member_has_no_active_license(
    service: ReconciliationService, store: RoleSyncFakeStore
) -> None:
    product_id = uuid.uuid4()
    plan = _plan(guild_id=1, product_id=product_id, role_id=999)
    store.plans.append(plan)

    player = _player(discord_id=111)
    store.players[player.id] = player
    # sem License ACTIVE pra este player+produto — cargo e divergencia

    role = MagicMock(spec=discord.Role)
    member = _member(111, roles=[role])
    guild = _guild_with_role(1, role, role_members=[member])

    result = await service.reconcile_guild(guild)

    member.remove_roles.assert_awaited_once()
    assert result.roles_removed == 1
    assert result.roles_granted == 0
    assert len(store.audit_calls) == 1


async def test_no_divergence_when_license_matches_role(
    service: ReconciliationService, store: RoleSyncFakeStore
) -> None:
    product_id = uuid.uuid4()
    plan = _plan(guild_id=1, product_id=product_id, role_id=999)
    store.plans.append(plan)

    player = _player(discord_id=111)
    store.players[player.id] = player
    store.licenses[uuid.uuid4()] = _license(player.id, product_id)

    role = MagicMock(spec=discord.Role)
    member = _member(111, roles=[role])
    guild = _guild_with_role(1, role, role_members=[member])
    guild.get_member.side_effect = lambda mid: member if mid == 111 else None

    result = await service.reconcile_guild(guild)

    member.remove_roles.assert_not_called()
    member.add_roles.assert_not_called()
    assert result.roles_granted == 0
    assert result.roles_removed == 0
    assert store.audit_calls == []


async def test_grants_role_when_license_active_but_role_missing(
    service: ReconciliationService, store: RoleSyncFakeStore
) -> None:
    product_id = uuid.uuid4()
    plan = _plan(guild_id=1, product_id=product_id, role_id=999)
    store.plans.append(plan)

    player = _player(discord_id=222)
    store.players[player.id] = player
    store.licenses[uuid.uuid4()] = _license(player.id, product_id)

    role = MagicMock(spec=discord.Role)
    member = _member(222, roles=[])  # sem o cargo
    guild = _guild_with_role(1, role, role_members=[])
    guild.get_member.side_effect = lambda mid: member if mid == 222 else None

    result = await service.reconcile_guild(guild)

    member.add_roles.assert_awaited_once()
    assert result.roles_granted == 1
    assert len(store.audit_calls) == 1


async def test_member_not_cached_in_guild_is_skipped(
    service: ReconciliationService, store: RoleSyncFakeStore
) -> None:
    """Player com License ativa mas nao esta no cache local de membros da
    guild (saiu do servidor, ou cache frio) — reconciliacao nao tenta
    fetch remoto caro, so pula."""
    product_id = uuid.uuid4()
    plan = _plan(guild_id=1, product_id=product_id, role_id=999)
    store.plans.append(plan)

    player = _player(discord_id=333)
    store.players[player.id] = player
    store.licenses[uuid.uuid4()] = _license(player.id, product_id)

    role = MagicMock(spec=discord.Role)
    guild = _guild_with_role(1, role, role_members=[])
    guild.get_member.return_value = None

    result = await service.reconcile_guild(guild)

    assert result.roles_granted == 0
    assert result.errors == 0


async def test_ignores_plans_without_role_or_product(
    service: ReconciliationService, store: RoleSyncFakeStore
) -> None:
    plan_no_role = Plan(guild_id=1, name="Sem cargo", product_id=uuid.uuid4(), role_id=None)
    plan_no_role.id = uuid.uuid4()
    plan_no_product = Plan(guild_id=1, name="Sem produto", product_id=None, role_id=123)
    plan_no_product.id = uuid.uuid4()
    store.plans.extend([plan_no_role, plan_no_product])

    guild = MagicMock(spec=discord.Guild)
    guild.id = 1

    result = await service.reconcile_guild(guild)

    guild.get_role.assert_not_called()
    assert result.roles_granted == 0
    assert result.roles_removed == 0


async def test_reconcile_all_guilds_aggregates_per_guild(
    service: ReconciliationService, store: RoleSyncFakeStore, bot: MagicMock
) -> None:
    product_id = uuid.uuid4()
    plan = _plan(guild_id=1, product_id=product_id, role_id=999)
    store.plans.append(plan)
    player = _player(discord_id=111)
    store.players[player.id] = player

    role = MagicMock(spec=discord.Role)
    member = _member(111, roles=[role])
    guild = _guild_with_role(1, role, role_members=[member])
    bot.guilds = [guild]

    report = await service.reconcile_all_guilds()

    assert report.guilds_checked == 1
    assert report.roles_removed == 1
    assert len(report.per_guild) == 1
    assert report.per_guild[0].guild_id == 1


async def test_plan_error_is_isolated_and_counted(
    service: ReconciliationService, store: RoleSyncFakeStore
) -> None:
    product_id = uuid.uuid4()
    plan = _plan(guild_id=1, product_id=product_id, role_id=999)
    store.plans.append(plan)

    guild = MagicMock(spec=discord.Guild)
    guild.id = 1
    guild.get_role.side_effect = RuntimeError("boom")

    result = await service.reconcile_guild(guild)

    assert result.errors == 1
