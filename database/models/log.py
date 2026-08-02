from __future__ import annotations

import enum
import uuid

from sqlalchemy import BigInteger, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class LogAction(enum.Enum):
    CLAIM = "claim"
    UNCLAIM = "unclaim"
    FECHAMENTO = "fechamento"
    AVALIACAO = "avaliacao"
    RANKING_ALTERADO = "ranking_alterado"
    ERRO = "erro"
    ATUALIZACAO_AUTOMATICA = "atualizacao_automatica"
    CONFIG_ALTERADA = "config_alterada"
    REABERTURA = "reabertura"
    SPAM_DETECTADO = "spam_detectado"
    BLACKLIST_ACAO = "blacklist_acao"
    EXCLUSAO = "exclusao"


class LogEntry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Tabela de auditoria. FKs sao SET NULL: o log sobrevive ao registro apagado."""

    __tablename__ = "logs"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    action: Mapped[LogAction] = mapped_column(Enum(LogAction, name="log_action"), nullable=False)
    actor_discord_id: Mapped[int | None] = mapped_column(BigInteger)
    staff_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("staff.id", ondelete="SET NULL"), nullable=True
    )
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True
    )
    category_snapshot: Mapped[str | None] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(Text, nullable=False)
