from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


def _utcnow() -> datetime:
    return datetime.now(UTC)


class StaffStats(Base, UUIDPrimaryKeyMixin):
    """1 linha por staff, atualizada incrementalmente pelos services."""

    __tablename__ = "staff_stats"

    staff_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("staff.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    tickets_assumidos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tickets_fechados: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tickets_cancelados: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avaliacoes_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avaliacao_media: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False, default=0)
    melhor_avaliacao: Mapped[int | None] = mapped_column(SmallInteger)
    pior_avaliacao: Mapped[int | None] = mapped_column(SmallInteger)
    tempo_medio_primeira_resposta_s: Mapped[int | None] = mapped_column(Integer)
    tempo_medio_fechamento_s: Mapped[int | None] = mapped_column(Integer)
    primeiro_ticket_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ultimo_ticket_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ticket_atual_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True
    )
    current_streak_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    best_streak_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_streak_date: Mapped[date | None] = mapped_column(Date)
    last_bad_rating_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_active_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_day_date: Mapped[date | None] = mapped_column(Date)
    current_day_ticket_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    best_day_ticket_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_perfect_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
