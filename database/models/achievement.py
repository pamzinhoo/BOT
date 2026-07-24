from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Achievement(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Conquista desbloqueada por um staff. `key` e fixa pras conquistas unicas
    (first_ticket, tickets_100, ...) e sufixada com ano-mes pra 'primeiro lugar
    do mes', que pode se repetir em meses diferentes."""

    __tablename__ = "achievements"
    __table_args__ = (UniqueConstraint("staff_id", "key", name="uq_achievement_staff_key"),)

    staff_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("staff.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
