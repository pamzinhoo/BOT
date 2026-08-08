from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


def _utcnow() -> datetime:
    return datetime.now(UTC)


class GuildSettings(Base, UUIDPrimaryKeyMixin):
    """1 linha por guild com todos os IDs configuraveis do bot."""

    __tablename__ = "guild_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    log_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    ranking_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    ranking_message_id: Mapped[int | None] = mapped_column(BigInteger)
    reports_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    evaluations_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    moderator_role_id: Mapped[int | None] = mapped_column(BigInteger)
    dev_role_id: Mapped[int | None] = mapped_column(BigInteger)
    ceo_role_id: Mapped[int | None] = mapped_column(BigInteger)
    owner_role_id: Mapped[int | None] = mapped_column(BigInteger)
    support_role_id: Mapped[int | None] = mapped_column(BigInteger)
    partner_role_id: Mapped[int | None] = mapped_column(BigInteger)
    streamer_role_id: Mapped[int | None] = mapped_column(BigInteger)
    inactive_after_minutes: Mapped[int | None] = mapped_column(Integer)
    ticket_category_id: Mapped[int | None] = mapped_column(BigInteger)
    ticket_alert_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    transcript_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    blacklist_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    backup_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    dashboard_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    dashboard_message_id: Mapped[int | None] = mapped_column(BigInteger)
    log_punishments_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    appeal_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    appeal_category_id: Mapped[int | None] = mapped_column(BigInteger)
    max_timeout_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    review_role_id: Mapped[int | None] = mapped_column(BigInteger)
    review_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    review_timeout_minutes: Mapped[int | None] = mapped_column(Integer)
    player_role_id: Mapped[int | None] = mapped_column(BigInteger)
    verified_role_id: Mapped[int | None] = mapped_column(BigInteger)
    moderation_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    require_proof: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    extra_config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
