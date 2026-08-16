from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Index, Integer, text
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TicketCategory(enum.Enum):
    BUG = "bug"
    DENUNCIA = "denuncia"
    DUVIDA = "duvida"
    SUGESTAO = "sugestao"
    PARCERIA = "parceria"
    OUTRO = "outro"


class TicketApprovalStatus(enum.Enum):
    """Etapa opcional de aprovacao — so usada por tickets criados por um painel
    com `approval_enabled`. NONE = painel sem aprovacao (padrao)."""

    NONE = "none"
    PENDING = "pending"
    APPROVED = "approved"
    REPROVED = "reproved"


class TicketStatus(enum.Enum):
    OPEN = "open"
    CLAIMED = "claimed"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class Ticket(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """1 linha por ticket. channel_id e unico: 1 canal = 1 ticket."""

    __tablename__ = "tickets"
    __table_args__ = (
        Index(
            "ix_tickets_open_by_guild_member",
            "guild_id", "opened_by_discord_id",
            postgresql_where=text("status IN ('OPEN', 'CLAIMED')"),
        ),
        Index(
            "ix_tickets_staff_created",
            "claimed_by_staff_id", text("created_at DESC"),
        ),
    )

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    opened_by_discord_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    category: Mapped[TicketCategory] = mapped_column(
        Enum(TicketCategory, name="ticket_category"), nullable=False
    )
    status: Mapped[TicketStatus] = mapped_column(
        Enum(TicketStatus, name="ticket_status"), nullable=False, default=TicketStatus.OPEN
    )
    claimed_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("staff.id", ondelete="SET NULL"), nullable=True
    )
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by_discord_id: Mapped[int | None] = mapped_column(BigInteger)
    deleted_before_service: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    counts_for_stats: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reminder_tier_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    voice_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    # painel que originou o ticket. NULL = fluxo legado (/painel-setup) ou
    # ticket criado sem painel nenhum.
    panel_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ticket_panels.id", ondelete="SET NULL"), nullable=True
    )
    approval_status: Mapped[TicketApprovalStatus] = mapped_column(
        Enum(TicketApprovalStatus, name="ticket_approval_status"),
        nullable=False,
        default=TicketApprovalStatus.NONE,
    )
    approval_reviewed_by: Mapped[int | None] = mapped_column(BigInteger)
    approval_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
