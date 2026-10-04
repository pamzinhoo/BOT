from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, GuildScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class RedemptionCode(Base, GuildScopedMixin, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "redemption_codes"
    __table_args__ = (
        UniqueConstraint("guild_id", "code", name="uq_redemption_code_guild"),
        CheckConstraint(
            "code ~ '^[A-Z0-9]{8}$' AND code ~ '[A-Z]' AND code ~ '[0-9]'",
            name="ck_redemption_code_format",
        ),
        CheckConstraint("max_uses IS NULL OR max_uses > 0", name="ck_redemption_max_uses"),
        CheckConstraint(
            "role_duration_seconds IS NULL OR role_duration_seconds > 0",
            name="ck_redemption_duration",
        ),
        CheckConstraint("reward_type IN ('message', 'role')", name="ck_redemption_reward"),
        CheckConstraint("delivery IN ('channel', 'dm')", name="ck_redemption_delivery"),
        CheckConstraint(
            "(reward_type = 'role' AND role_id IS NOT NULL) OR (reward_type = 'message' AND role_id IS NULL AND role_duration_seconds IS NULL)",
            name="ck_redemption_role",
        ),
        CheckConstraint(
            "role_duration_seconds IS NULL OR temporary_role_ack",
            name="ck_redemption_temporary_ack",
        ),
        CheckConstraint(
            "starts_at IS NULL OR expires_at IS NULL OR starts_at < expires_at",
            name="ck_redemption_dates",
        ),
    )

    code: Mapped[str] = mapped_column(String(8), nullable=False)
    reward_type: Mapped[str] = mapped_column(String(12), nullable=False)
    role_id: Mapped[int | None] = mapped_column(BigInteger)
    role_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    temporary_role_ack: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    delivery: Mapped[str] = mapped_column(String(12), nullable=False, default="channel")
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_uses: Mapped[int | None] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class RedemptionRoleGrant(Base, GuildScopedMixin, UUIDPrimaryKeyMixin, TimestampMixin):
    """One durable owner/lease per member role, shared across codes."""

    __tablename__ = "redemption_role_grants"
    __table_args__ = (
        UniqueConstraint("guild_id", "user_id", "role_id", name="uq_redemption_member_role"),
        Index("ix_redemption_grant_due", "status", "expires_at"),
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    owns_role: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    permanent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    origin_redemption_id: Mapped[uuid.UUID | None] = mapped_column()
    lease_token: Mapped[uuid.UUID | None] = mapped_column()
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(String(300))


class Redemption(Base, GuildScopedMixin, UUIDPrimaryKeyMixin, TimestampMixin):
    """Immutable reward snapshot. Failed attempts release capacity, never erase history."""

    __tablename__ = "redemptions"
    __table_args__ = (
        UniqueConstraint("code_id", "user_id", name="uq_redemption_code_user"),
        Index("ix_redemption_pending", "status", "next_attempt_at"),
        Index("ix_redemption_notification_due", "notification_status", "updated_at"),
        Index("ix_redemption_grant_status", "grant_id", "status"),
    )
    code_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("redemption_codes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    grant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("redemption_role_grants.id", ondelete="RESTRICT")
    )
    reward_type: Mapped[str] = mapped_column(String(12), nullable=False)
    role_id: Mapped[int | None] = mapped_column(BigInteger)
    role_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    delivery: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    notification_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    role_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(300))
