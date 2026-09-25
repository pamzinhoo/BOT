from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, GuildScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class EventTimerStatus(enum.Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    FINISHED = "FINISHED"
    CANCELED = "CANCELED"
    ERROR = "ERROR"


class EventTimer(Base, GuildScopedMixin, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "event_timers"

    creator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger)

    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    mention_everyone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    repeat_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    next_announcement_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_announcement_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[EventTimerStatus] = mapped_column(
        Enum(EventTimerStatus, name="event_timer_status"),
        nullable=False,
        default=EventTimerStatus.ACTIVE,
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(1000))

    image_storage_path: Mapped[str | None] = mapped_column(String(1000))
    image_filename: Mapped[str | None] = mapped_column(String(255))
    image_content_type: Mapped[str | None] = mapped_column(String(100))
    image_size: Mapped[int | None] = mapped_column(Integer)
    image_delete_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
