from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TicketFormResponse(Base, UUIDPrimaryKeyMixin):
    """Resposta que o usuario deu a uma pergunta do formulario ao abrir o ticket.

    `field_label` e um snapshot do texto da pergunta (de proposito, sem FK pro
    TicketPanelFormField): se o admin editar/apagar a pergunta depois, as
    respostas historicas continuam legiveis."""

    __tablename__ = "ticket_form_responses"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    field_label: Mapped[str] = mapped_column(String(45), nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
