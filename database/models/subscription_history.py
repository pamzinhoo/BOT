from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SubscriptionEventType(enum.Enum):
    CREATED = "created"
    RENEWED = "renewed"
    CANCELED = "canceled"
    UPGRADED = "upgraded"
    DOWNGRADED = "downgraded"
    EXPIRED = "expired"


class SubscriptionHistory(Base, UUIDPrimaryKeyMixin):
    """Trilha de auditoria imutavel de tudo que aconteceu com uma assinatura —
    nunca atualizada, so inserida. Base pro historico exibido no painel."""

    __tablename__ = "subscription_history"

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[SubscriptionEventType] = mapped_column(
        Enum(SubscriptionEventType, name="subscription_event_type"), nullable=False
    )
    from_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("plans.id", ondelete="SET NULL")
    )
    to_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("plans.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
