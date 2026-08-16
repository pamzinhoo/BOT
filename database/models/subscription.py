from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class BillingCycle(enum.Enum):
    MONTHLY = "monthly"
    YEARLY = "yearly"
    ONE_TIME = "one_time"


class SubscriptionStatus(enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    CANCELED = "canceled"
    EXPIRED = "expired"


class Subscription(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """1 linha por assinatura ativa/historica de um usuario a um plano de uma
    guild. `external_reference` e a chave de idempotencia usada pelo gateway
    (PaymentProvider) pra nunca processar a mesma cobranca duas vezes."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("guild_id", "user_id", "plan_id", name="uq_subscription_guild_user_plan"),
        Index("ix_subscriptions_guild_status", "guild_id", "status"),
    )

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False)

    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, name="subscription_status"),
        nullable=False,
        default=SubscriptionStatus.PENDING,
    )
    billing_cycle: Mapped[BillingCycle] = mapped_column(
        Enum(BillingCycle, name="subscription_billing_cycle"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    external_reference: Mapped[str | None] = mapped_column(String(200), unique=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
