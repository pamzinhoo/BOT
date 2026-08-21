from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


def _utcnow() -> datetime:
    return datetime.now(UTC)


class MonetizationSettings(Base, UUIDPrimaryKeyMixin):
    """1 linha por guild — configuracao geral do modulo de Monetizacao
    (canais usados pela loja/aprovacao manual/log), nunca preco ou plano."""

    __tablename__ = "monetization_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    shop_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    shop_message_id: Mapped[int | None] = mapped_column(BigInteger)
    approval_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    log_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    dlc_announcement_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
