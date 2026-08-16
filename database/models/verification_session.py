from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin
from database.models.verification_settings import VerificationMethod


def _utcnow() -> datetime:
    return datetime.now(UTC)


class VerificationSessionStatus(enum.Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    EXPIRED = "expired"
    MAX_ATTEMPTS_EXCEEDED = "max_attempts_exceeded"
    CANCELLED = "cancelled"


class VerificationSession(Base, UUIDPrimaryKeyMixin):
    """Uma verificacao (CAPTCHA) ativa/concluida de um usuario numa guild.

    Nunca reutilizada: cada tentativa errada troca `code` (e incrementa
    `generation`, que invalida qualquer botao/mensagem anterior) sem criar uma
    nova linha — o registro inteiro e removido/encerrado (status != PENDING)
    apos sucesso ou expiracao. Sem FK pra tickets/pagamentos — tabela propria,
    isolada do resto do sistema."""

    __tablename__ = "verification_sessions"
    __table_args__ = (
        Index("ix_verification_sessions_guild_user", "guild_id", "user_id"),
        Index(
            "ix_verification_sessions_pending_expires",
            "expires_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
    )

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    method: Mapped[VerificationMethod] = mapped_column(
        Enum(VerificationMethod, name="verification_method"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    case_sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    decoys: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # incrementado a cada regeneracao de codigo (erro) — usado no custom_id dos
    # botoes pra invalidar qualquer botao de uma geracao anterior.
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    status: Mapped[VerificationSessionStatus] = mapped_column(
        Enum(VerificationSessionStatus, name="verification_session_status"),
        nullable=False,
        default=VerificationSessionStatus.PENDING,
    )
    attempts_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)

    via_dm: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    delivery_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(BigInteger)

    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
