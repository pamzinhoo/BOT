from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


def _utcnow() -> datetime:
    return datetime.now(UTC)


class VerificationMethod(enum.Enum):
    TYPE = "type"
    BUTTON = "button"
    RANDOM = "random"


class CodeCharset(enum.Enum):
    LETTERS = "letters"
    NUMBERS = "numbers"
    ALPHANUMERIC = "alphanumeric"


class VerificationExceededAction(enum.Enum):
    NONE = "none"
    RESTART = "restart"
    KICK = "kick"
    BAN = "ban"


class VerificationSettings(Base, UUIDPrimaryKeyMixin):
    """1 linha por guild — configuracao do sistema de verificacao/CAPTCHA
    (/config -> Verificação). Mensagens ficam None ate a staff personalizar;
    nesse caso o servico usa um texto padrao (nunca fixo/obrigatorio, so um
    fallback editavel), igual ao padrao ja usado em Booster/Ticket.

    method/code_charset/on_max_attempts_action/on_expire_action guardam o
    `.value` (string) do enum correspondente, nao o tipo Enum do Postgres —
    mesma convencao de outras categorias do painel com campo CHOICE (ex.:
    RankingSettings.criteria, AntiSpamSettings.default_action), porque o
    DomainSettingsView generico grava a string crua do SelectOption."""

    __tablename__ = "verification_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    method: Mapped[str] = mapped_column(
        String(20), nullable=False, default=VerificationMethod.TYPE.value
    )
    unverified_role_id: Mapped[int | None] = mapped_column(BigInteger)
    verified_role_id: Mapped[int | None] = mapped_column(BigInteger)
    verification_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    log_channel_id: Mapped[int | None] = mapped_column(BigInteger)

    code_length: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    code_charset: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CodeCharset.ALPHANUMERIC.value
    )
    case_sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    timeout_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=10)

    welcome_message: Mapped[str | None] = mapped_column(Text)
    success_message: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    expired_message: Mapped[str | None] = mapped_column(Text)
    max_attempts_message: Mapped[str | None] = mapped_column(Text)

    on_max_attempts_action: Mapped[str] = mapped_column(
        String(20), nullable=False, default=VerificationExceededAction.NONE.value
    )
    on_expire_action: Mapped[str] = mapped_column(
        String(20), nullable=False, default=VerificationExceededAction.NONE.value
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
