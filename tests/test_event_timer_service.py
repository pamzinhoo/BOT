from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from database.models.event_timer import EventTimer, EventTimerStatus
from services.event_timer_service import EventTimerService, EventTimerValidationError


class DummySettings:
    storage_configured = False


class DummyBot:
    settings = DummySettings()


@pytest.mark.asyncio
async def test_create_rejects_short_repeat_interval():
    service = EventTimerService(database=None, bot=DummyBot())  # type: ignore[arg-type]
    with pytest.raises(EventTimerValidationError, match="intervalo minimo"):
        await service.create(
            guild_id=1,
            creator_id=1,
            channel_id=1,
            title="Teste",
            description=None,
            ends_at=datetime.now(UTC) + timedelta(hours=1),
            repeat_interval_seconds=30,
        )


@pytest.mark.asyncio
async def test_create_rejects_image_when_storage_unconfigured():
    service = EventTimerService(database=None, bot=DummyBot())  # type: ignore[arg-type]
    with pytest.raises(EventTimerValidationError, match="Storage"):
        await service.create(
            guild_id=1,
            creator_id=1,
            channel_id=1,
            title="Teste",
            description=None,
            ends_at=datetime.now(UTC) + timedelta(hours=1),
            repeat_interval_seconds=60,
            image_bytes=b"abc",
            image_filename="evento.png",
            image_content_type="image/png",
        )


def test_event_timer_status_values():
    assert EventTimerStatus.ACTIVE.value == "ACTIVE"
    assert EventTimerStatus.PAUSED.value == "PAUSED"
    assert EventTimerStatus.FINISHED.value == "FINISHED"
    assert EventTimer.__tablename__ == "event_timers"
