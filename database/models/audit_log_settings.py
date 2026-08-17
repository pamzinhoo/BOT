from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AuditLogSettings(Base, UUIDPrimaryKeyMixin):
    """1 linha por guild. Um Boolean por categoria de AuditLogCategory (ver audit_log.py)."""

    __tablename__ = "audit_log_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    channel_id: Mapped[int | None] = mapped_column(BigInteger)

    ban: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    kick: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    timeout: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    role_update: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    nickname: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    channel_update: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    category_update: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    permission_update: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    channel_create_delete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    role_create_delete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    message_delete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    message_edit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    bulk_delete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    voice_join_leave: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    voice_move: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    mute_unmute: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deaf_undeaf: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    bot_added: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    emoji: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sticker: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    server_config: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    tickets: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    punishment_appeal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    punishment_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    payment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enquete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    subscription: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    coupon: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    plan: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    verification: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    partnership: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    giveaway: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    product: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
