from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Device(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """1 linha por dispositivo (maquina) onde o Launcher rodou. `device_uuid` e
    gerado pelo proprio Launcher na primeira execucao e persistido localmente
    — nao deriva de fingerprint de hardware (formatacao/troca de peca nao
    invalida o dispositivo). Revogar um Device (`revoked=True`) mata em
    cascata as LauncherSession associadas — ver LauncherSessionRepository.
    """

    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("player_id", "device_uuid", name="uq_devices_player_uuid"),)

    player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)

    label: Mapped[str | None] = mapped_column(String(100))
    os_info: Mapped[str | None] = mapped_column(String(200))
    launcher_version: Mapped[str | None] = mapped_column(String(32))

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_ip: Mapped[str | None] = mapped_column(INET)

    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(String(200))
