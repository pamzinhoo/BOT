from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Claim(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Historico completo de claim/unclaim (N por ticket)."""

    __tablename__ = "claims"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False
    )
    staff_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("staff.id", ondelete="CASCADE"), nullable=False
    )
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    unclaimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
