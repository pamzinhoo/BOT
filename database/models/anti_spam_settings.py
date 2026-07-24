from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AntiSpamSettings(Base, UUIDPrimaryKeyMixin):
    """1 linha por guild — thresholds do anti-spam. Valores default = os que
    hoje estao hardcoded em cogs/antispam.py."""

    __tablename__ = "anti_spam_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    cross_channel_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    flood_window_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    flood_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    repeat_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    ignore_staff: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    default_action: Mapped[str] = mapped_column(String(20), nullable=False, default="alerta")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
