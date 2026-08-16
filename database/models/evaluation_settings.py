from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin

# Onde a avaliacao do ticket fica disponivel pro usuario. "ticket" preserva o
# comportamento historico (unico valor que existia antes desta config) —
# guildas antigas sem essa coluna (import de config anterior, linha ja
# existente no banco antes da migration) caem aqui via default/server_default.
EVALUATION_METHODS: dict[str, str] = {
    "ticket": "💬 Somente no Ticket",
    "dm": "📨 Somente por DM",
    "both": "💬📨 Ticket + DM",
}
DEFAULT_EVALUATION_METHOD = "ticket"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class EvaluationSettings(Base, UUIDPrimaryKeyMixin):
    """1 linha por guild — regras de avaliação de atendimento."""

    __tablename__ = "evaluation_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # default=2 preserva o comportamento antigo (comentario obrigatorio pra nota <=2)
    min_comment_rating: Mapped[int | None] = mapped_column(Integer, default=2)
    star_emoji: Mapped[str] = mapped_column(String(20), nullable=False, default="⭐")
    # "ticket" | "dm" | "both" — onde o botao de avaliar aparece depois do
    # fechamento (ver EVALUATION_METHODS acima).
    evaluation_method: Mapped[str] = mapped_column(
        String(8), nullable=False, default=DEFAULT_EVALUATION_METHOD
    )
    # personalizacao da DM de avaliacao — cada campo None cai num texto padrao
    # (ver views/embeds.py:evaluation_dm_embed), mesmo padrao de fallback ja
    # usado nos campos embed_* de TicketPanel.
    dm_embed_title: Mapped[str | None] = mapped_column(String(256))
    dm_embed_description: Mapped[str | None] = mapped_column(Text)
    dm_prompt_text: Mapped[str | None] = mapped_column(Text)
    dm_button_label: Mapped[str | None] = mapped_column(String(80))
    dm_thanks_message: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
