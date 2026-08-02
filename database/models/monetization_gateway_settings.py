from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


def _utcnow() -> datetime:
    return datetime.now(UTC)


class MonetizationGatewaySettings(Base, UUIDPrimaryKeyMixin):
    """1 linha por guild — qual gateway de pagamento a guild usa e como. As
    credenciais reais (access token/webhook secret) NUNCA ficam aqui — vem so
    de variavel de ambiente (config/settings.py). `enable_card`/`enable_boleto`
    ficam persistidos pra uso futuro; o fluxo de compra atual so gera cobranca
    PIX independente desses toggles."""

    __tablename__ = "monetization_gateway_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    environment: Mapped[str] = mapped_column(String(20), nullable=False, default="sandbox")
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="BRL")
    pix_expiration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    allow_recurring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allow_one_time: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enable_pix: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enable_card: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enable_boleto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
