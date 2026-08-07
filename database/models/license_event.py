from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


class LicenseEventType(enum.Enum):
    CREATED = "created"
    RENEWED = "renewed"
    REVOKED = "revoked"
    EXPIRED = "expired"
    REACTIVATED = "reactivated"


class LicenseEvent(Base, UUIDPrimaryKeyMixin):
    """Historico imutavel de mudancas de status de uma License — mesmo papel
    que SubscriptionHistory tem hoje pra Subscription. So `occurred_at`, sem
    updated_at: linha de historico nunca e editada."""

    __tablename__ = "license_events"

    license_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("licenses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[LicenseEventType] = mapped_column(
        Enum(LicenseEventType, name="license_event_type"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text)
    event_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
