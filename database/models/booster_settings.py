from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


def _utcnow() -> datetime:
    return datetime.now(UTC)


class BoosterSettings(Base, UUIDPrimaryKeyMixin):
    """1 linha por guild — configuracao do sistema de Boosters (/config -> Boost).
    dm_message/public_message ficam None ate a staff personalizar; nesse caso o
    servico usa um texto padrao (nunca fixo/obrigatorio, so um fallback editavel)."""

    __tablename__ = "booster_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    booster_role_id: Mapped[int | None] = mapped_column(BigInteger)
    dm_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    dm_message: Mapped[str | None] = mapped_column(Text)
    log_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    public_message_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    public_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    public_message: Mapped[str | None] = mapped_column(Text)
    public_use_embed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
