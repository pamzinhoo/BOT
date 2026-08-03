from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AutoModCategory(enum.Enum):
    OFENSA = "ofensa"
    DISCRIMINACAO = "discriminacao"
    GOLPE_SPAM = "golpe_spam"
    SEXUAL_ILEGAL = "sexual_ilegal"
    PRIVACIDADE = "privacidade"
    AMEACA_ASSEDIO = "ameaca_assedio"
    SUSPEITA = "suspeita"
    PERSONALIZADA = "personalizada"


class AutoModRiskLevel(enum.Enum):
    BAIXO = "baixo"
    MEDIO = "medio"
    ALTO = "alto"


class AutoModWord(Base, UUIDPrimaryKeyMixin):
    """automod_config — palavras monitoradas por guild. Cobre tanto palavras
    personalizadas adicionadas via /automod adicionar (is_builtin=False) quanto
    overrides de supressao de palavras padrao via /automod remover (is_builtin=True,
    active=False — a lista padrao em si vive em codigo, nao no banco)."""

    __tablename__ = "automod_config"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    palavra: Mapped[str] = mapped_column(String(200), nullable=False)
    categoria: Mapped[AutoModCategory] = mapped_column(
        Enum(AutoModCategory, name="automod_category"), nullable=False
    )
    nivel: Mapped[AutoModRiskLevel] = mapped_column(
        Enum(AutoModRiskLevel, name="automod_risk_level"), nullable=False
    )
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    added_by_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class AutoModSettings(Base, UUIDPrimaryKeyMixin):
    """1 linha por guild — liga/desliga o AutoMod e configura punicoes/excecoes."""

    __tablename__ = "automod_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    medio_timeout_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    alto_timeout_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=1440)
    alto_use_ban: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    alert_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    ignored_channel_ids: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    ignored_role_ids: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    allowed_words: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class AutoModLog(Base, UUIDPrimaryKeyMixin):
    """automod_logs — 1 linha por deteccao/acao automatica aplicada."""

    __tablename__ = "automod_logs"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_name: Mapped[str | None] = mapped_column(String(100))
    channel_id: Mapped[int | None] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    mensagem: Mapped[str] = mapped_column(Text, nullable=False)
    palavra_detectada: Mapped[str] = mapped_column(String(200), nullable=False)
    categoria: Mapped[AutoModCategory] = mapped_column(
        Enum(AutoModCategory, name="automod_category"), nullable=False
    )
    nivel: Mapped[AutoModRiskLevel] = mapped_column(
        Enum(AutoModRiskLevel, name="automod_risk_level"), nullable=False
    )
    punicao_aplicada: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
