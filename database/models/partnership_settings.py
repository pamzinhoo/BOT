from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PartnershipMode(enum.Enum):
    CHANNEL = "channel"
    FORUM = "forum"


class PartnershipSettings(Base, UUIDPrimaryKeyMixin):
    """1 linha por guild — configuracao do sistema de parcerias (/config ->
    Parcerias). `mode` guarda o `.value` (string) do enum, nao o tipo Enum do
    Postgres — mesma convencao de outras categorias do painel com campo
    CHOICE (ver VerificationSettings).

    O cargo Parceiro/Streamer NAO tem coluna aqui — reaproveita
    GuildSettings.partner_role_id (/config -> Cargos), que ja existia
    exatamente pra isso (registro central de cargos importantes da guild)."""

    __tablename__ = "partnership_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default=PartnershipMode.CHANNEL.value)
    category_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    forum_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    staff_role_id: Mapped[int | None] = mapped_column(BigInteger)
    cooldown_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    allow_here: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    pre_message: Mapped[str | None] = mapped_column(Text)
    log_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    max_description_length: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    allow_banner: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_image: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_invite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_external_links: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
