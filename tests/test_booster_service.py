from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import discord
import pytest

from database.models.booster_settings import BoosterSettings
from services.booster_service import BoosterService, render_placeholders


def _fake_member(*, guild_name: str = "Servidor Teste", member_count: int = 42) -> discord.Member:
    guild = MagicMock(spec=discord.Guild)
    guild.name = guild_name
    guild.member_count = member_count

    member = MagicMock(spec=discord.Member)
    member.mention = "<@123>"
    member.guild = guild
    return member


def _fake_role(name: str = "Booster") -> discord.Role:
    role = MagicMock(spec=discord.Role)
    role.mention = "<@&456>"
    role.name = name
    return role


def test_renders_all_placeholders() -> None:
    member = _fake_member()
    role = _fake_role()

    result = render_placeholders(
        "{user} impulsionou {server_name}, ganhou {role_name}, boost #{boost_count}, "
        "somos {member_count} membros.",
        member=member,
        role=role,
        boost_count=3,
    )

    assert result == (
        "<@123> impulsionou Servidor Teste, ganhou <@&456>, boost #3, somos 42 membros."
    )


def test_role_placeholder_falls_back_when_role_not_configured() -> None:
    member = _fake_member()

    result = render_placeholders("Cargo: {role_name}", member=member, role=None, boost_count=1)

    assert result == "Cargo: —"


# --- cache de get_settings ------------------------------------------------


class _FakeSession:
    async def flush(self) -> None:
        pass

    async def refresh(self, entity: object) -> None:
        pass


class _FakeDatabase:
    @asynccontextmanager
    async def session(self):
        yield _FakeSession()


class _CountingBoosterSettingsRepository:
    calls = 0
    store: dict[int, BoosterSettings] = {}

    def __init__(self, session: object) -> None:
        pass

    async def get_or_create(self, guild_id: int) -> BoosterSettings:
        type(self).calls += 1
        if guild_id not in self.store:
            settings = BoosterSettings(guild_id=guild_id)
            settings.id = guild_id  # unico o bastante pro teste
            self.store[guild_id] = settings
        return self.store[guild_id]


@pytest.fixture
def counting_repo(monkeypatch) -> type[_CountingBoosterSettingsRepository]:
    _CountingBoosterSettingsRepository.calls = 0
    _CountingBoosterSettingsRepository.store = {}
    monkeypatch.setattr(
        "services.booster_service.BoosterSettingsRepository", _CountingBoosterSettingsRepository
    )
    return _CountingBoosterSettingsRepository


async def test_get_settings_hits_repository_once_then_caches(counting_repo) -> None:
    service = BoosterService(_FakeDatabase(), bot=MagicMock())

    await service.get_settings(1)
    await service.get_settings(1)
    await service.get_settings(1)

    assert counting_repo.calls == 1


async def test_get_settings_cache_is_scoped_per_guild(counting_repo) -> None:
    service = BoosterService(_FakeDatabase(), bot=MagicMock())

    await service.get_settings(1)
    await service.get_settings(2)

    assert counting_repo.calls == 2


async def test_update_settings_invalidates_cache(counting_repo) -> None:
    service = BoosterService(_FakeDatabase(), bot=MagicMock())

    await service.get_settings(1)
    await service.update_settings(1, enabled=False)
    await service.get_settings(1)

    # 1 do get inicial (cache miss) + 1 do proprio update_settings (le antes
    # de mutar, sempre direto no repo) + 1 do get seguinte (cache invalidada)
    assert counting_repo.calls == 3
