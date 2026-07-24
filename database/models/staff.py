from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Staff(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Identidade de um membro da staff (1 linha por membro por guild)."""

    __tablename__ = "staff"
    __table_args__ = (UniqueConstraint("guild_id", "discord_user_id", name="uq_staff_guild_user"),)

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    discord_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
