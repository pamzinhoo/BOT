from __future__ import annotations

import enum
import uuid

from sqlalchemy import BigInteger, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AppealStatus(enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class AppealMethod(enum.Enum):
    BUTTON = "button"
    DM_MESSAGE = "dm_message"


class PunishmentAppeal(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """1 linha por recurso enviado pelo usuario punido (Etapa 15-21).
    1 punicao so pode ter 1 recurso (controle anti-abuso na service/repository)."""

    __tablename__ = "punishment_appeals"

    punishment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("punishments.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message: Mapped[str] = mapped_column(String(2000), nullable=False)
    additional_info: Mapped[str | None] = mapped_column(String(2000))
    status: Mapped[AppealStatus] = mapped_column(
        Enum(AppealStatus, name="appeal_status"), nullable=False, default=AppealStatus.PENDING
    )
    method: Mapped[AppealMethod] = mapped_column(
        Enum(AppealMethod, name="appeal_method"), nullable=False, default=AppealMethod.BUTTON
    )
    reviewed_by_id: Mapped[int | None] = mapped_column(BigInteger)
    reviewed_by_name: Mapped[str | None] = mapped_column(String(100))
    review_reason: Mapped[str | None] = mapped_column(String(1024))
    channel_message_id: Mapped[int | None] = mapped_column(BigInteger)
