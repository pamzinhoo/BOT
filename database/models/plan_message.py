from __future__ import annotations

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


class PlanMessageType(enum.Enum):
    PURCHASE = "purchase"
    RENEWAL = "renewal"
    CANCELLATION = "cancellation"
    THANK_YOU = "thank_you"
    UPGRADE = "upgrade"
    DOWNGRADE = "downgrade"


class PlanMessage(Base, UUIDPrimaryKeyMixin):
    """1 linha por (plano, tipo de mensagem) — cada evento do ciclo de vida da
    assinatura pode ter um texto proprio, totalmente editavel pelo admin. Sem
    linha cadastrada = servico usa um fallback generico (nunca obrigatorio)."""

    __tablename__ = "plan_messages"
    __table_args__ = (UniqueConstraint("plan_id", "message_type", name="uq_plan_message_type"),)

    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
    )
    message_type: Mapped[PlanMessageType] = mapped_column(
        Enum(PlanMessageType, name="plan_message_type"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
