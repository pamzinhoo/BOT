from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, Enum, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AuditLogCategory(enum.Enum):
    BAN = "ban"
    KICK = "kick"
    TIMEOUT = "timeout"
    ROLE_UPDATE = "role_update"
    NICKNAME = "nickname"
    CHANNEL_UPDATE = "channel_update"
    CATEGORY_UPDATE = "category_update"
    PERMISSION_UPDATE = "permission_update"
    CHANNEL_CREATE_DELETE = "channel_create_delete"
    ROLE_CREATE_DELETE = "role_create_delete"
    MESSAGE_DELETE = "message_delete"
    MESSAGE_EDIT = "message_edit"
    BULK_DELETE = "bulk_delete"
    VOICE_JOIN_LEAVE = "voice_join_leave"
    VOICE_MOVE = "voice_move"
    MUTE_UNMUTE = "mute_unmute"
    DEAF_UNDEAF = "deaf_undeaf"
    BOT_ADDED = "bot_added"
    EMOJI = "emoji"
    STICKER = "sticker"
    SERVER_CONFIG = "server_config"
    TICKETS = "tickets"
    PUNISHMENT_APPEAL = "punishment_appeal"
    PUNISHMENT_REVIEW = "punishment_review"
    ENQUETE = "enquete"
    PAYMENT = "payment"
    SUBSCRIPTION = "subscription"
    COUPON = "coupon"
    PLAN = "plan"
    VERIFICATION = "verification"
    PARTNERSHIP = "partnership"
    GIVEAWAY = "giveaway"


class AuditLogEntry(Base, UUIDPrimaryKeyMixin):
    """1 linha por evento auditado. Sem FK pra nada — o audit log tem que sobreviver a tudo."""

    __tablename__ = "audit_log_entries"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    category: Mapped[AuditLogCategory] = mapped_column(
        Enum(AuditLogCategory, name="audit_log_category"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    executor_id: Mapped[int | None] = mapped_column(BigInteger)
    executor_name: Mapped[str | None] = mapped_column(String(100))
    target_id: Mapped[int | None] = mapped_column(BigInteger)
    target_name: Mapped[str | None] = mapped_column(String(100))
    reason: Mapped[str | None] = mapped_column(String(512))
    details: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    # usados so quando category == SERVER_CONFIG (historico do /config)
    config_category: Mapped[str | None] = mapped_column(String(50))
    config_name: Mapped[str | None] = mapped_column(String(100))
    old_value: Mapped[str | None] = mapped_column(String(512))
    new_value: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
