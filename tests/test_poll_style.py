from __future__ import annotations

import uuid

import discord

from database.models.poll import PollOption
from utils.poll_style import (
    DEFAULT_BUTTON_STYLE,
    discord_button_style,
    option_dot,
    parse_option_line,
)


def _option(*, emoji: str | None = None, button_style: str = "secondary") -> PollOption:
    option = PollOption(poll_id=uuid.uuid4(), name="Opção", position=0, emoji=emoji, button_style=button_style)
    option.id = uuid.uuid4()
    return option


# --- parse_option_line -------------------------------------------------


def test_parse_option_line_name_only() -> None:
    name, emoji, style = parse_option_line("Sim")
    assert name == "Sim"
    assert emoji is None
    assert style == DEFAULT_BUTTON_STYLE


def test_parse_option_line_with_emoji_and_color() -> None:
    name, emoji, style = parse_option_line("Sim | ✅ | verde")
    assert name == "Sim"
    assert emoji == "✅"
    assert style == "success"


def test_parse_option_line_color_keywords() -> None:
    assert parse_option_line("A | | verde")[2] == "success"
    assert parse_option_line("A | | vermelho")[2] == "danger"
    assert parse_option_line("A | | azul")[2] == "primary"
    assert parse_option_line("A | | cinza")[2] == "secondary"


def test_parse_option_line_unknown_color_falls_back_to_secondary() -> None:
    _name, _emoji, style = parse_option_line("A | | roxo")
    assert style == "secondary"


def test_parse_option_line_trims_whitespace() -> None:
    name, emoji, style = parse_option_line("  Sim  |  ✅  |  verde  ")
    assert name == "Sim"
    assert emoji == "✅"
    assert style == "success"


def test_parse_option_line_empty_emoji_segment_is_none() -> None:
    name, emoji, style = parse_option_line("Sim | | verde")
    assert name == "Sim"
    assert emoji is None
    assert style == "success"


# --- discord_button_style -----------------------------------------------


def test_discord_button_style_maps_known_styles() -> None:
    assert discord_button_style("success") == discord.ButtonStyle.success
    assert discord_button_style("danger") == discord.ButtonStyle.danger
    assert discord_button_style("primary") == discord.ButtonStyle.primary
    assert discord_button_style("secondary") == discord.ButtonStyle.secondary


def test_discord_button_style_unknown_falls_back_to_secondary() -> None:
    assert discord_button_style("nao-existe") == discord.ButtonStyle.secondary


# --- option_dot -----------------------------------------------------


def test_option_dot_uses_custom_emoji_when_set() -> None:
    option = _option(emoji="🔥", button_style="success")
    assert option_dot(option) == "🔥"


def test_option_dot_falls_back_to_color_dot_by_style() -> None:
    assert option_dot(_option(button_style="success")) == "🟢"
    assert option_dot(_option(button_style="danger")) == "🔴"
    assert option_dot(_option(button_style="primary")) == "🔵"
    assert option_dot(_option(button_style="secondary")) == "⚪"
