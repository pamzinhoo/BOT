from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AuditLogLauncherAction(enum.Enum):
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    REFRESH_ROTATED = "refresh_rotated"
    REFRESH_REUSE_DETECTED = "refresh_reuse_detected"
    LOGOUT = "logout"
    LOGOUT_ALL = "logout_all"
    DEVICE_REVOKED = "device_revoked"
    RATE_LIMITED = "rate_limited"


class AuditLogLauncher(Base, UUIDPrimaryKeyMixin):
    """1 linha por evento sensivel do fluxo de autenticacao do Launcher.
    Tabela separada de `audit_log_entries` (essa e guild-scoped, do bot de
    Discord; o ecossistema Launcher/Player e global — ver
    bot/docs/LIMERENCE_LAUNCHER_ARCHITECTURE.md secao 2). Sem FK real pra
    Player/Device de proposito, igual AuditLogEntry: audit log tem que
    sobreviver mesmo se a linha referenciada for removida."""

    __tablename__ = "audit_log_launcher"

    player_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    action: Mapped[AuditLogLauncherAction] = mapped_column(
        Enum(AuditLogLauncherAction, name="audit_log_launcher_action"), nullable=False, index=True
    )
    ip_address: Mapped[str | None] = mapped_column(INET)
    audit_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
