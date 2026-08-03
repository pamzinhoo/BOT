from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PartnershipMentionType(enum.Enum):
    NONE = "none"
    HERE = "here"
    EVERYONE = "everyone"


class PartnershipRoleRemovedAction(enum.Enum):
    NONE = "none"
    ARCHIVE = "archive"
    DELETE = "delete"


class PartnershipSettings(Base, UUIDPrimaryKeyMixin):
    """1 linha por guild — configuracao do sistema de parcerias (/config ->
    Parcerias).

    O cargo Parceiro/Streamer NAO tem coluna aqui — reaproveita
    GuildSettings.partner_role_id / GuildSettings.streamer_role_id (/config ->
    Cargos), que ja existiam exatamente pra isso (registro central de cargos
    importantes da guild)."""

    __tablename__ = "partnership_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # categoria ativa (canais de parceiros em uso) e categoria pra onde o
    # canal vai quando o parceiro perde o cargo.
    category_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    archive_category_id: Mapped[int | None] = mapped_column(BigInteger)

    staff_role_id: Mapped[int | None] = mapped_column(BigInteger)
    log_channel_id: Mapped[int | None] = mapped_column(BigInteger)

    auto_create: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    auto_move: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    role_removed_action: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PartnershipRoleRemovedAction.ARCHIVE.value
    )

    welcome_message: Mapped[str | None] = mapped_column(Text)

    announcement_message: Mapped[str | None] = mapped_column(Text)
    announcement_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    announcement_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    mention_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PartnershipMentionType.NONE.value
    )
    last_announcement_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
