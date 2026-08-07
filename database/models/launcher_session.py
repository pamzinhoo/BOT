from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class LauncherSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """1 linha por refresh token emitido pro Launcher. Nome nao e `Session`
    de proposito — colidiria com `sqlalchemy.orm.Session` em todo import.

    `refresh_token_hash` e SEMPRE o hash (sha256) do token, nunca o valor em
    claro — o backend nao consegue reconstituir o token a partir da linha.
    Rotacao: cada uso de refresh invalida esta linha (`revoked_at`) e cria uma
    nova — reuso de um token ja revogado e sinal de roubo (ver
    docs/LIMERENCE_LAUNCHER_ARCHITECTURE.md secao 3.1).
    """

    __tablename__ = "launcher_sessions"

    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    refresh_token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    jwt_key_id: Mapped[str | None] = mapped_column(String(32))

    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_ip: Mapped[str | None] = mapped_column(INET)

    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(String(200))
