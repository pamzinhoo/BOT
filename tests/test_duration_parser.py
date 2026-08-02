from __future__ import annotations

from datetime import timedelta

import pytest

from utils.time import InvalidDurationError, parse_duration


@pytest.mark.parametrize(
    "value, expected",
    [
        ("10m", timedelta(minutes=10)),
        ("30m", timedelta(minutes=30)),
        ("24h", timedelta(hours=24)),
        ("7d", timedelta(days=7)),
    ],
)
def test_parse_duration_accepts_valid_formats(value: str, expected: timedelta) -> None:
    assert parse_duration(value) == expected


@pytest.mark.parametrize("value", ["30", "horas", "1 semana", "abc", "", "0m", "-5h"])
def test_parse_duration_rejects_invalid_formats(value: str) -> None:
    with pytest.raises(InvalidDurationError):
        parse_duration(value)
