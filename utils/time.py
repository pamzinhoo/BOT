from __future__ import annotations

import re
from datetime import timedelta

_DURATION_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_DURATION_PATTERN = re.compile(r"^(\d+)\s*([smhd])$", re.IGNORECASE)


class InvalidDurationError(ValueError):
    """Duracao informada nao bate com o formato esperado (ex.: 24h, 30m, 7d)."""


def parse_duration(value: str) -> timedelta:
    """Converte '24h', '30m', '7d', '45s' num timedelta. Levanta InvalidDurationError
    se o formato nao for reconhecido ou o valor for zero."""
    match = _DURATION_PATTERN.match(value.strip())
    if match is None:
        raise InvalidDurationError(
            f"Duração inválida: {value!r}. Use o formato número+unidade, ex.: 24h, 30m, 7d."
        )
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if amount <= 0:
        raise InvalidDurationError("Duração precisa ser maior que zero.")
    return timedelta(seconds=amount * _DURATION_UNIT_SECONDS[unit])


def humanize_duration(seconds: int | None) -> str:
    """Formata segundos como '7m 12s' ou '1h 3m'. None vira '—'."""
    if seconds is None:
        return "—"
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
