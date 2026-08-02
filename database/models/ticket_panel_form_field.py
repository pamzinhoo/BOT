from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# Modal do Discord aceita no maximo 5 componentes — o limite e validado no
# TicketPanelService (add_form_field) e na UI, nunca truncado em silencio.
MAX_FORM_FIELDS = 5

FORM_FIELD_STYLES: dict[str, str] = {
    "short": "Curta (uma linha)",
    "long": "Longa (paragrafo)",
}


class TicketPanelFormField(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Uma pergunta do formulario opcional de um painel de tickets. As perguntas
    viram um modal mostrado antes da criacao do canal."""

    __tablename__ = "ticket_panel_form_fields"

    panel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ticket_panels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    label: Mapped[str] = mapped_column(String(45), nullable=False)
    style: Mapped[str] = mapped_column(String(16), nullable=False, default="short")
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    placeholder: Mapped[str | None] = mapped_column(String(100))
