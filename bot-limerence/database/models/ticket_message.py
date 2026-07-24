from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


class TicketMessageKind(enum.Enum):
    USER_FIRST = "user_first"
    STAFF_FIRST = "staff_first"


class TicketMessage(Base, UUIDPrimaryKeyMixin):
    """So a primeira mensagem do usuario e a primeira resposta da staff.

    Existe pra sustentar anti-fraude ("fechado sem receber mensagem do
    usuario") e o calculo de tempo de primeira resposta, sem guardar o
    historico de chat inteiro.
    """

    __tablename__ = "ticket_messages"
    __table_args__ = (UniqueConstraint("ticket_id", "kind", name="uq_ticket_message_kind"),)

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[TicketMessageKind] = mapped_column(
        Enum(TicketMessageKind, name="ticket_message_kind"), nullable=False
    )
    discord_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    author_discord_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
