from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ScheduledJobState(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "scheduled_job_state"
    __table_args__ = (
        UniqueConstraint("guild_id", "job_name", name="uq_scheduled_job_state_guild_job"),
    )

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    job_name: Mapped[str] = mapped_column(String(length=80), nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
