from __future__ import annotations

import inspect
from datetime import UTC, datetime, time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cogs.backup import BackupCog, _backup_period_start


def _cog() -> BackupCog:
    cog = object.__new__(BackupCog)
    cog.bot = SimpleNamespace(
        settings=SimpleNamespace(backup_daily_hour_utc=5),
        guilds=[SimpleNamespace(id=123)],
    )
    cog._check_monthly_top1 = AsyncMock()
    cog._backup_guild = AsyncMock()
    cog._mark_backup_success = AsyncMock()
    return cog


def test_restart_does_not_schedule_relative_immediate_backup() -> None:
    assert BackupCog.daily_backup._time == [time(hour=5, tzinfo=UTC)]
    assert "tasks.loop(time=" in inspect.getsource(BackupCog)
    assert "tasks.loop(hours=24)" not in inspect.getsource(BackupCog)


@pytest.mark.asyncio
async def test_backup_already_done_in_period_is_not_sent_again() -> None:
    cog = _cog()
    cog._try_begin_backup = AsyncMock(return_value=False)

    await BackupCog._run(cog, now=datetime(2026, 9, 7, 5, 0, tzinfo=UTC))

    cog._backup_guild.assert_not_awaited()
    cog._mark_backup_success.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_backup_does_not_update_last_success_at() -> None:
    cog = _cog()
    cog._try_begin_backup = AsyncMock(return_value=True)
    cog._backup_guild = AsyncMock(side_effect=RuntimeError("boom"))

    await BackupCog._run(cog, now=datetime(2026, 9, 7, 5, 0, tzinfo=UTC))

    cog._mark_backup_success.assert_not_awaited()


@pytest.mark.asyncio
async def test_next_valid_backup_attempt_can_succeed() -> None:
    cog = _cog()
    cog._try_begin_backup = AsyncMock(side_effect=[False, True])

    await BackupCog._run(cog, now=datetime(2026, 9, 7, 5, 0, tzinfo=UTC))
    await BackupCog._run(cog, now=datetime(2026, 9, 8, 5, 0, tzinfo=UTC))

    cog._backup_guild.assert_awaited_once()
    cog._mark_backup_success.assert_awaited_once_with(123)


def test_backup_period_uses_fixed_daily_calendar() -> None:
    assert _backup_period_start(datetime(2026, 9, 7, 14, 0, tzinfo=UTC), 5) == datetime(
        2026, 9, 7, 5, 0, tzinfo=UTC
    )
    assert _backup_period_start(datetime(2026, 9, 7, 4, 59, tzinfo=UTC), 5) == datetime(
        2026, 9, 6, 5, 0, tzinfo=UTC
    )
