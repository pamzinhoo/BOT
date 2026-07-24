from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DashboardSettings(Base, UUIDPrimaryKeyMixin):
    """1 linha por guild — comportamento do dashboard da staff."""

    __tablename__ = "dashboard_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    auto_update_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    update_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    top_count: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    show_chart: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
