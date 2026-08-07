from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from core.events import LICENSE_CREATED, LICENSE_REVOKED, LicenseEventPayload
from database.models.plan import Plan
from database.models.player import Player
from services.role_sync_service import RoleSyncService
from tests._fakes_role_sync import (
    FakeAuditLogService,
    FakeDatabase,
    RoleSyncFakeStore,
    install_role_sync_fakes,
)


def _player(discord_id: int) -> Player:
    player = Player(discord_id=discord_id, discord_username="tester", linked_at=datetime.now(UTC))
    player.id = uuid.uuid4()
    return player


def _plan(*, guild_id: int, product_id: uuid.UUID, role_id: int) -> Plan:
    plan = Plan(guild_id=guild_id, name="Patrono", product_id=product_id, role_id=role_id)
    plan.id = uuid.uuid4()
    return plan


def _member(discord_id: int, *, has_role: bool, role: discord.Role) -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.id = discord_id
    member.roles = [role] if has_role else []
    member.add_roles = AsyncMock()
    member.remove_roles = AsyncMock()
    return member


def _guild(guild_id: int, *, role: discord.Role, member: discord.Member | None) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    guild.get_role.return_value = role
    guild.get_member.return_value = member
    guild.fetch_member = AsyncMock(return_value=member)
    return guild


@pytest.fixture
def store() -> RoleSyncFakeStore:
    return RoleSyncFakeStore()


@pytest.fixture
def bot(store: RoleSyncFakeStore) -> MagicMock:
    fake_bot = MagicMock()
    fake_bot.audit_log_service = FakeAuditLogService(store)
    return fake_bot


@pytest.fixture
def role_sync_service(monkeypatch, store: RoleSyncFakeStore, bot: MagicMock) -> RoleSyncService:
    install_role_sync_fakes(monkeypatch, store)
    return RoleSyncService(FakeDatabase(store), bot)


async def test_grant_event_adds_role_when_missing(
    role_sync_service: RoleSyncService, store: RoleSyncFakeStore, bot: MagicMock
) -> None:
    product_id = uuid.uuid4()
    player = _player(discord_id=111)
    plan = _plan(guild_id=1, product_id=product_id, role_id=999)
    store.players[player.id] = player
    store.plans.append(plan)

    role = MagicMock(spec=discord.Role)
    member = _member(111, has_role=False, role=role)
    guild = _guild(1, role=role, member=member)
    bot.get_guild.return_value = guild

    payload = LicenseEventPayload(
        license_id=uuid.uuid4(), player_id=player.id, product_id=product_id,
        status="active", event_type=LICENSE_CREATED, occurred_at=datetime.now(UTC),
    )
    await role_sync_service.handle_license_event(payload)

    member.add_roles.assert_awaited_once()
    member.remove_roles.assert_not_called()
    assert len(store.audit_calls) == 1
    assert store.audit_calls[0]["action"] == "Cargo concedido (evento de licenca)"


async def test_grant_event_is_noop_when_role_already_present(
    role_sync_service: RoleSyncService, store: RoleSyncFakeStore, bot: MagicMock
) -> None:
    product_id = uuid.uuid4()
    player = _player(discord_id=111)
    plan = _plan(guild_id=1, product_id=product_id, role_id=999)
    store.players[player.id] = player
    store.plans.append(plan)

    role = MagicMock(spec=discord.Role)
    member = _member(111, has_role=True, role=role)
    bot.get_guild.return_value = _guild(1, role=role, member=member)

    payload = LicenseEventPayload(
        license_id=uuid.uuid4(), player_id=player.id, product_id=product_id,
        status="active", event_type=LICENSE_CREATED, occurred_at=datetime.now(UTC),
    )
    await role_sync_service.handle_license_event(payload)

    member.add_roles.assert_not_called()
    assert store.audit_calls == []


async def test_revoke_event_removes_role_when_present(
    role_sync_service: RoleSyncService, store: RoleSyncFakeStore, bot: MagicMock
) -> None:
    product_id = uuid.uuid4()
    player = _player(discord_id=222)
    plan = _plan(guild_id=1, product_id=product_id, role_id=999)
    store.players[player.id] = player
    store.plans.append(plan)

    role = MagicMock(spec=discord.Role)
    member = _member(222, has_role=True, role=role)
    bot.get_guild.return_value = _guild(1, role=role, member=member)

    payload = LicenseEventPayload(
        license_id=uuid.uuid4(), player_id=player.id, product_id=product_id,
        status="revoked", event_type=LICENSE_REVOKED, occurred_at=datetime.now(UTC),
    )
    await role_sync_service.handle_license_event(payload)

    member.remove_roles.assert_awaited_once()
    assert store.audit_calls[0]["action"] == "Cargo removido (evento de licenca)"


async def test_revoke_event_noop_when_role_absent(
    role_sync_service: RoleSyncService, store: RoleSyncFakeStore, bot: MagicMock
) -> None:
    product_id = uuid.uuid4()
    player = _player(discord_id=222)
    plan = _plan(guild_id=1, product_id=product_id, role_id=999)
    store.players[player.id] = player
    store.plans.append(plan)

    role = MagicMock(spec=discord.Role)
    member = _member(222, has_role=False, role=role)
    bot.get_guild.return_value = _guild(1, role=role, member=member)

    payload = LicenseEventPayload(
        license_id=uuid.uuid4(), player_id=player.id, product_id=product_id,
        status="revoked", event_type=LICENSE_REVOKED, occurred_at=datetime.now(UTC),
    )
    await role_sync_service.handle_license_event(payload)

    member.remove_roles.assert_not_called()
    assert store.audit_calls == []


async def test_no_matching_plan_is_noop(role_sync_service: RoleSyncService, store: RoleSyncFakeStore) -> None:
    player = _player(discord_id=333)
    store.players[player.id] = player

    payload = LicenseEventPayload(
        license_id=uuid.uuid4(), player_id=player.id, product_id=uuid.uuid4(),
        status="active", event_type=LICENSE_CREATED, occurred_at=datetime.now(UTC),
    )
    await role_sync_service.handle_license_event(payload)  # nao levanta, so nao faz nada


async def test_unknown_player_is_noop(role_sync_service: RoleSyncService, store: RoleSyncFakeStore) -> None:
    payload = LicenseEventPayload(
        license_id=uuid.uuid4(), player_id=uuid.uuid4(), product_id=uuid.uuid4(),
        status="active", event_type=LICENSE_CREATED, occurred_at=datetime.now(UTC),
    )
    await role_sync_service.handle_license_event(payload)


async def test_syncs_role_across_multiple_guilds(
    role_sync_service: RoleSyncService, store: RoleSyncFakeStore, bot: MagicMock
) -> None:
    product_id = uuid.uuid4()
    player = _player(discord_id=444)
    store.players[player.id] = player
    plan_a = _plan(guild_id=1, product_id=product_id, role_id=10)
    plan_b = _plan(guild_id=2, product_id=product_id, role_id=20)
    store.plans.extend([plan_a, plan_b])

    role_a, role_b = MagicMock(spec=discord.Role), MagicMock(spec=discord.Role)
    member_a = _member(444, has_role=False, role=role_a)
    member_b = _member(444, has_role=False, role=role_b)
    guild_a = _guild(1, role=role_a, member=member_a)
    guild_b = _guild(2, role=role_b, member=member_b)
    bot.get_guild.side_effect = lambda gid: {1: guild_a, 2: guild_b}[gid]

    payload = LicenseEventPayload(
        license_id=uuid.uuid4(), player_id=player.id, product_id=product_id,
        status="active", event_type=LICENSE_CREATED, occurred_at=datetime.now(UTC),
    )
    await role_sync_service.handle_license_event(payload)

    member_a.add_roles.assert_awaited_once()
    member_b.add_roles.assert_awaited_once()
    assert len(store.audit_calls) == 2


async def test_one_guild_failure_does_not_block_the_other(
    role_sync_service: RoleSyncService, store: RoleSyncFakeStore, bot: MagicMock
) -> None:
    product_id = uuid.uuid4()
    player = _player(discord_id=555)
    store.players[player.id] = player
    plan_a = _plan(guild_id=1, product_id=product_id, role_id=10)
    plan_b = _plan(guild_id=2, product_id=product_id, role_id=20)
    store.plans.extend([plan_a, plan_b])

    role_b = MagicMock(spec=discord.Role)
    member_b = _member(555, has_role=False, role=role_b)
    guild_b = _guild(2, role=role_b, member=member_b)

    def _get_guild(gid: int):
        if gid == 1:
            raise RuntimeError("guild indisponivel")
        return guild_b

    bot.get_guild.side_effect = _get_guild

    payload = LicenseEventPayload(
        license_id=uuid.uuid4(), player_id=player.id, product_id=product_id,
        status="active", event_type=LICENSE_CREATED, occurred_at=datetime.now(UTC),
    )
    await role_sync_service.handle_license_event(payload)  # nao propaga a excecao

    member_b.add_roles.assert_awaited_once()
