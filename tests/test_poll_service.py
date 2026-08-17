from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from services.poll_service import EnqueteDisabledError, InvalidOptionsError, PollService
from tests._fakes_poll import FakeDatabase, FakeVoteWeightService, PollFakeStore, install_poll_fakes

_GUILD_ID = 1
_CREATOR_ID = 2
_CHANNEL_ID = 3


@pytest.fixture
def store() -> PollFakeStore:
    return PollFakeStore()


@pytest.fixture
def poll_service(monkeypatch, store: PollFakeStore) -> PollService:
    install_poll_fakes(monkeypatch, store)
    bot = MagicMock()
    return PollService(FakeDatabase(store), bot, FakeVoteWeightService(weight=1), MagicMock())


async def _enable(store: PollFakeStore, poll_service: PollService) -> None:
    await poll_service.get_settings(_GUILD_ID)  # cria a linha com enabled=True (fake default)


# --- criacao / parsing de opcoes -----------------------------------------


async def test_create_poll_parses_name_emoji_color_per_line(poll_service: PollService, store: PollFakeStore) -> None:
    await _enable(store, poll_service)
    poll, options = await poll_service.create_poll(
        guild_id=_GUILD_ID, creator_id=_CREATOR_ID, channel_id=_CHANNEL_ID,
        title="Facção de Estelionatários", description="Descrição",
        options=["Sim | ✅ | verde", "Não | ❌ | vermelho"],
        duration=timedelta(hours=1),
        image_url="https://example.com/logo.png",
    )

    assert poll.image_url == "https://example.com/logo.png"
    sim, nao = options
    assert sim.name == "Sim" and sim.emoji == "✅" and sim.button_style == "success"
    assert nao.name == "Não" and nao.emoji == "❌" and nao.button_style == "danger"


async def test_create_poll_plain_line_defaults_to_no_emoji_secondary(
    poll_service: PollService, store: PollFakeStore
) -> None:
    await _enable(store, poll_service)
    _poll, options = await poll_service.create_poll(
        guild_id=_GUILD_ID, creator_id=_CREATOR_ID, channel_id=_CHANNEL_ID,
        title="T", description=None, options=["Opção A", "Opção B"], duration=timedelta(hours=1),
    )
    assert all(o.emoji is None and o.button_style == "secondary" for o in options)


async def test_create_poll_rejects_too_few_options(poll_service: PollService, store: PollFakeStore) -> None:
    await _enable(store, poll_service)
    with pytest.raises(InvalidOptionsError):
        await poll_service.create_poll(
            guild_id=_GUILD_ID, creator_id=_CREATOR_ID, channel_id=_CHANNEL_ID,
            title="T", description=None, options=["Só uma"], duration=timedelta(hours=1),
        )


async def test_create_poll_rejects_too_many_options(poll_service: PollService, store: PollFakeStore) -> None:
    await _enable(store, poll_service)
    with pytest.raises(InvalidOptionsError):
        await poll_service.create_poll(
            guild_id=_GUILD_ID, creator_id=_CREATOR_ID, channel_id=_CHANNEL_ID,
            title="T", description=None, options=[f"Opção {i}" for i in range(11)], duration=timedelta(hours=1),
        )


async def test_create_poll_fails_when_disabled(poll_service: PollService) -> None:
    # sem chamar _enable -> settings ainda nao existe -> get_or_create cria com enabled=True no fake;
    # aqui forcamos disabled explicitamente pra testar o path negativo.
    settings = await poll_service.get_settings(_GUILD_ID)
    settings.enabled = False
    with pytest.raises(EnqueteDisabledError):
        await poll_service.create_poll(
            guild_id=_GUILD_ID, creator_id=_CREATOR_ID, channel_id=_CHANNEL_ID,
            title="T", description=None, options=["A", "B"], duration=timedelta(hours=1),
        )


# --- remocao de voto ---------------------------------------------------


async def test_remove_vote_returns_false_when_never_voted(poll_service: PollService, store: PollFakeStore) -> None:
    await _enable(store, poll_service)
    poll, _options = await poll_service.create_poll(
        guild_id=_GUILD_ID, creator_id=_CREATOR_ID, channel_id=_CHANNEL_ID,
        title="T", description=None, options=["A", "B"], duration=timedelta(hours=1),
    )
    removed = await poll_service.remove_vote(poll.id, 999)
    assert removed is False


async def test_remove_vote_deletes_existing_vote(poll_service: PollService, store: PollFakeStore) -> None:
    await _enable(store, poll_service)
    poll, options = await poll_service.create_poll(
        guild_id=_GUILD_ID, creator_id=_CREATOR_ID, channel_id=_CHANNEL_ID,
        title="T", description=None, options=["A", "B"], duration=timedelta(hours=1),
    )
    member = MagicMock()
    member.id = 42
    member.guild = MagicMock()
    await poll_service.cast_vote(poll, options[0].id, member)
    assert await poll_service.count_participants(poll.id) == 1

    removed = await poll_service.remove_vote(poll.id, 42)

    assert removed is True
    assert await poll_service.count_participants(poll.id) == 0


async def test_remove_vote_is_idempotent(poll_service: PollService, store: PollFakeStore) -> None:
    await _enable(store, poll_service)
    poll, options = await poll_service.create_poll(
        guild_id=_GUILD_ID, creator_id=_CREATOR_ID, channel_id=_CHANNEL_ID,
        title="T", description=None, options=["A", "B"], duration=timedelta(hours=1),
    )
    member = MagicMock()
    member.id = 42
    await poll_service.cast_vote(poll, options[0].id, member)

    first = await poll_service.remove_vote(poll.id, 42)
    second = await poll_service.remove_vote(poll.id, 42)

    assert first is True
    assert second is False  # nada mais pra remover — sem erro


# --- totals bruto vs ponderado ---------------------------------------------


async def test_raw_totals_vs_weighted_totals(poll_service: PollService, store: PollFakeStore) -> None:
    await _enable(store, poll_service)
    poll, options = await poll_service.create_poll(
        guild_id=_GUILD_ID, creator_id=_CREATOR_ID, channel_id=_CHANNEL_ID,
        title="T", description=None, options=["A", "B"], duration=timedelta(hours=1),
    )
    heavy_service = PollService(
        FakeDatabase(store), MagicMock(), FakeVoteWeightService(weight=5), MagicMock()
    )
    member = MagicMock()
    member.id = 7
    await heavy_service.cast_vote(poll, options[0].id, member)

    raw = await poll_service.raw_totals(poll.id)
    weighted = await poll_service.weighted_totals(poll.id)

    assert raw[options[0].id] == 1
    assert weighted[options[0].id] == 5


async def test_option_totals_combines_raw_and_weighted_in_one_call(
    poll_service: PollService, store: PollFakeStore
) -> None:
    await _enable(store, poll_service)
    poll, options = await poll_service.create_poll(
        guild_id=_GUILD_ID, creator_id=_CREATOR_ID, channel_id=_CHANNEL_ID,
        title="T", description=None, options=["A", "B"], duration=timedelta(hours=1),
    )
    heavy_service = PollService(
        FakeDatabase(store), MagicMock(), FakeVoteWeightService(weight=5), MagicMock()
    )
    member = MagicMock()
    member.id = 7
    await heavy_service.cast_vote(poll, options[0].id, member)

    totals = await poll_service.option_totals(poll.id)

    assert totals[options[0].id] == (1, 5)
    assert options[1].id not in totals
