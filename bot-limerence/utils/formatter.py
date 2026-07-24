from __future__ import annotations

from utils.constants import MEDALS


def rank_marker(position: int) -> str:
    """posicao 0-indexed -> medalha (top 3) ou 'N.' """
    if position < len(MEDALS):
        return MEDALS[position]
    return f"{position + 1}."


def format_rating(average: float) -> str:
    return f"⭐ {average:.1f}"


def running_average(old_avg: float | None, old_count: int, new_value: float) -> float:
    """Media incremental sem reler todas as amostras.

    old_count e a quantidade de amostras JA computadas em old_avg (antes desta nova).
    """
    if old_avg is None or old_count <= 0:
        return float(new_value)
    return ((old_avg * old_count) + new_value) / (old_count + 1)
