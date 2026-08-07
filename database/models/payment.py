from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PaymentStatus(enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELED = "canceled"
    REFUNDED = "refunded"
    CHARGEBACK = "chargeback"


class PaymentHistory(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """1 linha por cobranca processada por um PaymentProvider. `provider` +
    `external_id` sao unicos juntos — chave de idempotencia que impede
    processar o mesmo webhook/pagamento duas vezes (double-credit)."""

    __tablename__ = "payment_history"
    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_payment_provider_external_id"),
    )

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False)
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL")
    )

    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # centavos
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="BRL")
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status"), nullable=False, default=PaymentStatus.PENDING
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pix_qr_code: Mapped[str | None] = mapped_column(Text)
    pix_qr_code_base64: Mapped[str | None] = mapped_column(Text)
    checkout_url: Mapped[str | None] = mapped_column(String(500))
    # texto livre digitado pelo comprador ("quem vai pagar?") — nunca apagado,
    # mesmo apos aprovacao/rejeicao/expiracao (historico permanente).
    payer_information: Mapped[str | None] = mapped_column(Text)
