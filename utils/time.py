from __future__ import annotations


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
