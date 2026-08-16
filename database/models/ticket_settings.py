from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin

# Como as categorias (= paineis de ticket de um combo) sao apresentadas pra
# quem vai abrir o ticket. "buttons" = comportamento historico (um botao por
# painel); "select" = um String Select Menu unico com uma opcao por painel.
CATEGORY_SELECTION_MODES: dict[str, str] = {
    "buttons": "🟦 Botões",
    "select": "📋 Lista suspensa",
}
DEFAULT_CATEGORY_SELECTION_MODE = "buttons"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TicketSettings(Base, UUIDPrimaryKeyMixin):
    """1 linha por guild — comportamento do fluxo de tickets."""

    __tablename__ = "ticket_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    # kill switch global do sistema de tickets: desligado, nenhum painel (novo ou
    # legado) aceita abrir ticket, mas os tickets ja abertos continuam funcionando
    # normalmente (assumir/fechar/reabrir/transcricao).
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    max_tickets_per_user: Mapped[int | None] = mapped_column(Integer)
    allow_multiple_tickets: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    auto_close_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    delete_delay_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    # "buttons" | "select" — vale pros combos de paineis (varias categorias numa
    # mensagem so). Painel publicado sozinho continua com o botao dele, porque
    # ali nao existe escolha de categoria a fazer.
    category_selection_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DEFAULT_CATEGORY_SELECTION_MODE
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
