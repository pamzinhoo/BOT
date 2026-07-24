from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, ForeignKey, SmallInteger, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Evaluation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Avaliacao de um ticket. unique(ticket_id) trava '1 avaliacao por ticket'."""

    __tablename__ = "evaluations"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    staff_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("staff.id", ondelete="CASCADE"), nullable=False
    )
    rated_by_discord_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
