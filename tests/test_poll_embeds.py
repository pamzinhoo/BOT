from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from database.models.poll import Poll, PollOption, PollStatus, PollVisibility
from views.embeds import poll_live_embed


def _poll(*, status: PollStatus = PollStatus.OPEN, image_url: str | None = None, description: str | None = None) -> Poll:
    poll = Poll(
        guild_id=1,
        creator_id=2,
        channel_id=3,
        title="Facção de Estelionatários",
        description=description,
        status=status,
        visibility=PollVisibility.PUBLIC,
        weight_mode="SNAPSHOT",
        image_url=image_url,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    poll.id = uuid.uuid4()
    poll.closed_at = datetime.now(UTC) if status == PollStatus.CLOSED else None
    return poll


def _option(name: str, *, emoji: str | None = None, button_style: str = "secondary") -> PollOption:
    option = PollOption(poll_id=uuid.uuid4(), name=name, position=0, emoji=emoji, button_style=button_style)
    option.id = uuid.uuid4()
    return option


def test_poll_live_embed_open_state() -> None:
    poll = _poll(status=PollStatus.OPEN)
    embed = poll_live_embed(poll, [], {}, 0)

    assert embed.title == "Facção de Estelionatários"
    field_values = {f.name: f.value for f in embed.fields}
    assert field_values["Estado"] == "🟢 Aberta"
    assert "Encerra em" in field_values
    assert "Encerrada em" not in field_values
    assert embed.footer.text == "Enquete | Aether ©"


def test_poll_live_embed_closed_state() -> None:
    poll = _poll(status=PollStatus.CLOSED)
    embed = poll_live_embed(poll, [], {}, 0)

    field_values = {f.name: f.value for f in embed.fields}
    assert field_values["Estado"] == "🔴 Encerrada"
    assert "Encerrada em" in field_values
    assert "Encerra em" not in field_values


def test_poll_live_embed_description_is_italicized() -> None:
    poll = _poll(description="Texto da enquete")
    embed = poll_live_embed(poll, [], {}, 0)
    assert embed.description == "*Texto da enquete*"


def test_poll_live_embed_no_description_omits_field() -> None:
    poll = _poll(description=None)
    embed = poll_live_embed(poll, [], {}, 0)
    assert embed.description is None


def test_poll_live_embed_sets_thumbnail_when_image_url_present() -> None:
    poll = _poll(image_url="https://example.com/logo.png")
    embed = poll_live_embed(poll, [], {}, 0)
    assert embed.thumbnail.url == "https://example.com/logo.png"


def test_poll_live_embed_no_thumbnail_without_image_url() -> None:
    poll = _poll(image_url=None)
    embed = poll_live_embed(poll, [], {}, 0)
    assert embed.thumbnail.url is None


def test_poll_live_embed_shows_percent_and_dot_per_option() -> None:
    poll = _poll()
    sim = _option("Sim", emoji="✅", button_style="success")
    nao = _option("Não", emoji="❌", button_style="danger")
    totals = {sim.id: 27, nao.id: 39}

    embed = poll_live_embed(poll, [sim, nao], totals, 66)

    field_values = {f.name: f.value for f in embed.fields}
    assert field_values["✅ Sim"] == "27 voto(s) · 40.9%"
    assert field_values["❌ Não"] == "39 voto(s) · 59.1%"
    assert field_values["Participantes"] == "66"


def test_poll_live_embed_zero_votes_does_not_divide_by_zero() -> None:
    poll = _poll()
    option = _option("Sim")
    embed = poll_live_embed(poll, [option], {}, 0)
    field_values = {f.name: f.value for f in embed.fields}
    assert "0 voto(s) · 0.0%" in field_values.values()


def test_poll_live_embed_trophy_only_when_closed_with_votes() -> None:
    sim = _option("Sim", button_style="success")
    nao = _option("Não", button_style="danger")
    totals = {sim.id: 10, nao.id: 3}

    open_poll = _poll(status=PollStatus.OPEN)
    open_embed = poll_live_embed(open_poll, [sim, nao], totals, 13)
    assert not any(f.name.startswith("🏆") for f in open_embed.fields)

    closed_poll = _poll(status=PollStatus.CLOSED)
    closed_embed = poll_live_embed(closed_poll, [sim, nao], totals, 13)
    trophy_fields = [f for f in closed_embed.fields if f.name.startswith("🏆")]
    assert len(trophy_fields) == 1
    assert "Sim" in trophy_fields[0].name


def test_poll_live_embed_default_dot_matches_button_style_when_no_emoji() -> None:
    poll = _poll()
    option = _option("Talvez", emoji=None, button_style="primary")
    embed = poll_live_embed(poll, [option], {}, 0)
    assert any(f.name == "🔵 Talvez" for f in embed.fields)
