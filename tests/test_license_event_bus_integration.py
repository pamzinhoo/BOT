"""Integracao ponta a ponta do fluxo da Fase 5: LicenseService muda status ->
publica no EventBus -> RoleSyncService reage concedendo/removendo cargo. Sem
isso, os testes de unidade de cada servico (test_license_service.py,
test_role_sync_service.py) provam as partes isoladas mas nao provam que elas
estao de fato conectadas em core/bot.py."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from core.event_bus import EventBus
from services.license_service import LicenseService
from services.role_sync_service import RoleSyncService
from tests._fakes_license import FakeDatabase as LicenseFakeDatabase
from tests._fakes_license import LicenseFakeStore
from tests._fakes_license import install_fake_repositories as install_license_fakes
from tests._fakes_role_sync import FakeAuditLogService, RoleSyncFakeStore, install_role_sync_fakes
from tests._fakes_role_sync import FakeDatabase as RoleSyncFakeDatabase


@pytest.fixture
def license_store() -> LicenseFakeStore:
    return LicenseFakeStore()


@pytest.fixture
def role_store() -> RoleSyncFakeStore:
    return RoleSyncFakeStore()


@pytest.fixture
def bot(role_store: RoleSyncFakeStore) -> MagicMock:
    fake_bot = MagicMock()
    fake_bot.audit_log_service = FakeAuditLogService(role_store)
    return fake_bot


@pytest.fixture
def wired(monkeypatch, license_store: LicenseFakeStore, role_store: RoleSyncFakeStore, bot: MagicMock):
    install_license_fakes(monkeypatch, license_store)
    install_role_sync_fakes(monkeypatch, role_store)

    event_bus = EventBus()
    license_service = LicenseService(LicenseFakeDatabase(license_store), event_bus)
    role_sync_service = RoleSyncService(RoleSyncFakeDatabase(role_store), bot)
    role_sync_service.register(event_bus)
    return license_service, bot


async def test_grant_or_renew_ends_up_delivering_discord_role(wired, role_store: RoleSyncFakeStore) -> None:
    license_service, bot = wired
    player_id, product_id = uuid.uuid4(), uuid.uuid4()

    from datetime import UTC, datetime

    from database.models.plan import Plan
    from database.models.player import Player

    player = Player(discord_id=777, discord_username="tester", linked_at=datetime.now(UTC))
    player.id = player_id
    role_store.players[player_id] = player

    plan = Plan(guild_id=1, name="Patrono", product_id=product_id, role_id=555)
    plan.id = uuid.uuid4()
    role_store.plans.append(plan)

    role = MagicMock(spec=discord.Role)
    member = MagicMock(spec=discord.Member)
    member.id = 777
    member.roles = []
    member.add_roles = AsyncMock()
    member.remove_roles = AsyncMock()

    guild = MagicMock(spec=discord.Guild)
    guild.get_role.return_value = role
    guild.get_member.return_value = member
    bot.get_guild.return_value = guild

    await license_service.grant_or_renew(player_id, product_id, purchase_source="loja")

    member.add_roles.assert_awaited_once()
    assert len(role_store.audit_calls) == 1


async def test_revoke_ends_up_removing_discord_role(wired, role_store: RoleSyncFakeStore) -> None:
    license_service, bot = wired
    player_id, product_id = uuid.uuid4(), uuid.uuid4()

    from datetime import UTC, datetime

    from database.models.plan import Plan
    from database.models.player import Player

    player = Player(discord_id=888, discord_username="tester", linked_at=datetime.now(UTC))
    player.id = player_id
    role_store.players[player_id] = player

    plan = Plan(guild_id=1, name="Patrono", product_id=product_id, role_id=555)
    plan.id = uuid.uuid4()
    role_store.plans.append(plan)

    role = MagicMock(spec=discord.Role)
    member = MagicMock(spec=discord.Member)
    member.id = 888
    member.roles = [role]
    member.add_roles = AsyncMock()
    member.remove_roles = AsyncMock()

    guild = MagicMock(spec=discord.Guild)
    guild.get_role.return_value = role
    guild.get_member.return_value = member
    bot.get_guild.return_value = guild

    license_row = await license_service.grant_or_renew(player_id, product_id, purchase_source="loja")
    member.add_roles.reset_mock()  # so nos interessa o efeito da revogacao daqui pra frente

    await license_service.revoke(license_row.id, reason="teste")

    member.remove_roles.assert_awaited_once()


async def test_event_bus_failure_never_breaks_license_mutation(
    monkeypatch, license_store: LicenseFakeStore
) -> None:
    """Mesmo se o handler de role sync falhar (guild fora do ar, bug), a
    License ja foi commitada — o EventBus isola a falha do dominio de
    negocio que a publicou (core/event_bus.py: publish captura excecao)."""
    install_license_fakes(monkeypatch, license_store)

    event_bus = EventBus()

    async def broken_handler(payload):
        raise RuntimeError("RoleSyncService fora do ar")

    from core.events import LICENSE_CREATED

    event_bus.subscribe(LICENSE_CREATED, broken_handler)
    license_service = LicenseService(LicenseFakeDatabase(license_store), event_bus)

    license_row = await license_service.grant_or_renew(uuid.uuid4(), uuid.uuid4(), purchase_source="loja")

    assert license_row is not None
    assert len(license_store.licenses) == 1
