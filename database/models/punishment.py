from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PunishmentType(enum.Enum):
    BAN = "ban"
    BAN_TEMPORARIO = "ban_temporario"
    TIMEOUT = "timeout"
    KICK = "kick"
    ADVERTENCIA = "advertencia"


class PunishmentStatus(enum.Enum):
    PENDING = "pending"  # criada, aguardando 1a/2a confirmacao da staff
    NOTIFIED = "notified"  # DM de aviso entregue ao usuario, aguardando 2a confirmacao
    PENDING_REVIEW = "pending_review"  # isolada (cargo de analise), aguardando recurso ou expiracao
    ACTIVE = "active"  # aplicada de fato no Discord
    EXPIRED = "expired"
    REVOKED = "revoked"


# status que ainda nao viraram uma punicao de fato aplicada — usados pro
# check anti-duplicacao e pro anti-erro antes da 2a confirmacao (Etapa 3/5)
UNRESOLVED_STATUSES = {PunishmentStatus.PENDING, PunishmentStatus.NOTIFIED}

# tipos que suspendem o acesso do usuario e por isso permitem recurso (Etapa 15)
APPEALABLE_TYPES = {
    PunishmentType.BAN,
    PunishmentType.BAN_TEMPORARIO,
    PunishmentType.TIMEOUT,
    PunishmentType.KICK,
}


class Punishment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """1 linha por punicao. Criada em status PENDING assim que a staff passa pela
    1a confirmacao (Etapa 2/3) — so vira ACTIVE de fato depois da 2a confirmacao
    (Etapa 5), depois de tentar notificar o usuario por DM (Etapa 4).
    punishment_code e o ID publico (ex.: BAN-82931), id (UUID) e so uso interno."""

    __tablename__ = "punishments"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    punishment_code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_name: Mapped[str | None] = mapped_column(String(100))
    staff_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    staff_name: Mapped[str | None] = mapped_column(String(100))
    type: Mapped[PunishmentType] = mapped_column(Enum(PunishmentType, name="punishment_type"), nullable=False)
    reason: Mapped[str] = mapped_column(String(1024), nullable=False)
    proofs: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[PunishmentStatus] = mapped_column(
        Enum(PunishmentStatus, name="punishment_status"), nullable=False, default=PunishmentStatus.PENDING
    )

    # Etapa 4 — resultado da tentativa de notificacao por DM antes da punicao
    dm_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dm_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dm_failure_reason: Mapped[str | None] = mapped_column(Text)

    # anti-abuso (Etapa 2 do doc de melhorias) — auditoria da dupla confirmacao
    first_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    second_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # sistema de isolamento/analise (Etapa 22) — usuario fica com cargo de analise
    # em vez de levar a punicao real, ate recorrer ou o prazo expirar
    review_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    revoked_by_id: Mapped[int | None] = mapped_column(BigInteger)
    revoked_by_name: Mapped[str | None] = mapped_column(String(100))
    revoke_reason: Mapped[str | None] = mapped_column(String(1024))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
