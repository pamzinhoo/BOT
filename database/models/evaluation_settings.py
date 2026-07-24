from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
