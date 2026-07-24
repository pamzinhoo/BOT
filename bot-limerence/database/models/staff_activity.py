from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


class StaffActivityEvent(enum.Enum):
    CLAIM = "claim"
    UNCLAIM = "unclaim"
    CLOSED = "closed"


class StaffActivity(Base, UUIDPrimaryKeyMixin):
    """Eventos de negocio da staff (sem presenca online/offline)."""

    __tablename__ = "staff_activity"

    staff_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("staff.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[StaffActivityEvent] = mapped_column(
        Enum(StaffActivityEvent, name="staff_activity_event"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
