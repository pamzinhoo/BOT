from __future__ import annotations

from utils.appeal_dm import DMAppealRateLimiter, parse_recorrer_dm_command


def test_parse_recorrer_dm_command_valid() -> None:
    assert parse_recorrer_dm_command("!recorrer BAN-82931 motivo aqui") == (
        "BAN-82931",
        "motivo aqui",
    )


def test_parse_recorrer_dm_command_uppercases_code() -> None:
    assert parse_recorrer_dm_command("!recorrer ban-82931 motivo") == ("BAN-82931", "motivo")


def test_parse_recorrer_dm_command_ignores_other_messages() -> None:
    assert parse_recorrer_dm_command("oi tudo bem?") is None


def test_parse_recorrer_dm_command_missing_reason() -> None:
    assert parse_recorrer_dm_command("!recorrer BAN-82931") is None


def test_parse_recorrer_dm_command_missing_code() -> None:
    assert parse_recorrer_dm_command("!recorrer") is None


def test_parse_recorrer_dm_command_blank_reason() -> None:
    assert parse_recorrer_dm_command("!recorrer BAN-82931    ") is None


def test_rate_limiter_allows_up_to_max_attempts() -> None:
    limiter = DMAppealRateLimiter(max_attempts=3, window_seconds=60.0)
    assert limiter.allow(1, now=0.0)
    assert limiter.allow(1, now=1.0)
    assert limiter.allow(1, now=2.0)
    assert not limiter.allow(1, now=3.0)


def test_rate_limiter_is_per_user() -> None:
    limiter = DMAppealRateLimiter(max_attempts=1, window_seconds=60.0)
    assert limiter.allow(1, now=0.0)
    assert not limiter.allow(1, now=1.0)
    assert limiter.allow(2, now=1.0)


def test_rate_limiter_resets_after_window() -> None:
    limiter = DMAppealRateLimiter(max_attempts=1, window_seconds=10.0)
    assert limiter.allow(1, now=0.0)
    assert not limiter.allow(1, now=5.0)
    assert limiter.allow(1, now=11.0)
