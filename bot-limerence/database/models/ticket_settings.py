from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TicketSettings(Base, UUIDPrimaryKeyMixin):
    """1 linha por guild — comportamento do fluxo de tickets."""

    __tablename__ = "ticket_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    max_tickets_per_user: Mapped[int | None] = mapped_column(Integer)
    allow_multiple_tickets: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    auto_close_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    delete_delay_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
