from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin
from database.models.payment import PaymentStatus


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PaymentStatusHistory(Base, UUIDPrimaryKeyMixin):
    """Trilha de auditoria imutavel de toda transicao de status de um
    pagamento — nunca atualizada, so inserida. `provider_payload` guarda a
    resposta do gateway que originou a transicao (nunca token/segredo)."""

    __tablename__ = "payment_status_history"

    payment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payment_history.id", ondelete="CASCADE"), nullable=False
    )
    previous_status: Mapped[PaymentStatus | None] = mapped_column(
        Enum(PaymentStatus, name="payment_status")
    )
    new_status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status"), nullable=False
    )
    provider_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
