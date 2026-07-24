from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


def _utcnow() -> datetime:
    return datetime.now(UTC)


class BotStatusSettings(Base, UUIDPrimaryKeyMixin):
    """1 linha por guild — canal onde o bot posta e atualiza o painel de status
    (online/uptime/banco/gateway/tickets/staff) sempre editando a mesma mensagem."""

    __tablename__ = "bot_status_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    update_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
