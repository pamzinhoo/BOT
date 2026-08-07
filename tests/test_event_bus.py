from __future__ import annotations

import pytest

from core.event_bus import EventBus


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


async def test_publish_with_no_subscribers_is_noop(bus: EventBus) -> None:
    await bus.publish("SOMETHING", {"x": 1})  # nao levanta


async def test_subscriber_receives_payload(bus: EventBus) -> None:
    received = []

    async def handler(payload):
        received.append(payload)

    bus.subscribe("EVENT_A", handler)
    await bus.publish("EVENT_A", {"value": 42})

    assert received == [{"value": 42}]


async def test_multiple_subscribers_all_receive(bus: EventBus) -> None:
    calls = []

    async def handler_a(payload):
        calls.append(("a", payload))

    async def handler_b(payload):
        calls.append(("b", payload))

    bus.subscribe("EVENT_A", handler_a)
    bus.subscribe("EVENT_A", handler_b)
    await bus.publish("EVENT_A", "payload")

    assert ("a", "payload") in calls
    assert ("b", "payload") in calls


async def test_subscriber_only_receives_its_own_event(bus: EventBus) -> None:
    received = []

    async def handler(payload):
        received.append(payload)

    bus.subscribe("EVENT_A", handler)
    await bus.publish("EVENT_B", "should not arrive")

    assert received == []


async def test_failing_handler_does_not_block_others_or_propagate(bus: EventBus) -> None:
    calls = []

    async def failing_handler(payload):
        raise RuntimeError("boom")

    async def working_handler(payload):
        calls.append(payload)

    bus.subscribe("EVENT_A", failing_handler)
    bus.subscribe("EVENT_A", working_handler)

    await bus.publish("EVENT_A", "ok")  # nao propaga a excecao

    assert calls == ["ok"]
