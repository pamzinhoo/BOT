from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class LicenseStatus(enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class License(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """1 linha por posse (permanente ou recorrente) de um Product por um
    Player. Substitui o conceito de Subscription/DlcEntitlement — QUALQUER
    coisa vendida ou concedida vira uma License. `expires_at=NULL` = produto
    permanente (base game, DLC, cosmetico). `expires_at` preenchido = produto
    recorrente (`auto_renew` controla se renova sozinho).

    `external_reference` espelha o mesmo papel de idempotencia que tem em
    Subscription — chave unica do gateway de pagamento, pra nunca processar o
    mesmo pagamento duas vezes.
    """

    __tablename__ = "licenses"
    __table_args__ = (UniqueConstraint("player_id", "product_id", name="uq_licenses_player_product"),)

    player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("players.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    status: Mapped[LicenseStatus] = mapped_column(
        Enum(LicenseStatus, name="license_status"), nullable=False, default=LicenseStatus.PENDING, index=True
    )
    purchase_source: Mapped[str] = mapped_column(String(50), nullable=False)
    external_reference: Mapped[str | None] = mapped_column(String(200), unique=True)

    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auto_renew: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(String(200))
    granted_by_staff_id: Mapped[int | None] = mapped_column(BigInteger)
