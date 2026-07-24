from __future__ import annotations

import io
from typing import TYPE_CHECKING

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

if TYPE_CHECKING:
    from services.ranking_service import RankingEntry

_SURFACE = "#1a1a19"
_INK_PRIMARY = "#ffffff"
_INK_MUTED = "#898781"
_GRIDLINE = "#2c2c2a"
_BAR_COLOR = "#3987e5"


def render_ranking_chart(entries: list[RankingEntry]) -> bytes:
    """Barra horizontal com tickets fechados por staff (top N ja ordenado
    desc), estilo dark pra combinar com o tema padrao do Discord."""
    ordered = list(reversed(entries))
    names = [entry.staff.display_name for entry in ordered]
    values = [entry.tickets for entry in ordered]

    fig, ax = plt.subplots(figsize=(6, max(1.6, 0.55 * len(ordered) + 0.6)), dpi=160)
    fig.patch.set_facecolor(_SURFACE)
    ax.set_facecolor(_SURFACE)

    bars = ax.barh(names, values, color=_BAR_COLOR, height=0.55)

    ax.tick_params(colors=_INK_MUTED, length=0)
    for label in ax.get_yticklabels():
        label.set_color(_INK_PRIMARY)
        label.set_fontsize(10)
    ax.xaxis.set_visible(False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.grid(axis="x", color=_GRIDLINE, linewidth=0.8)
    ax.set_axisbelow(True)

    max_value = max(values, default=0)
    for bar, value in zip(bars, values):
        ax.text(
            bar.get_width() + max_value * 0.02 + 0.05,
            bar.get_y() + bar.get_height() / 2,
            str(value),
            va="center",
            ha="left",
            color=_INK_PRIMARY,
            fontsize=10,
            fontweight="bold",
        )

    fig.tight_layout(pad=0.6)
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", facecolor=_SURFACE)
    plt.close(fig)
    return buffer.getvalue()
