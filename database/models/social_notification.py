from __future__ import annotations

import enum

from sqlalchemy import BigInteger, Boolean, Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, GuildScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class SocialPlatform(enum.Enum):
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"
    TWITCH = "twitch"
    KICK = "kick"
    OTHER = "other"


class SocialNotificationStatus(enum.Enum):
    SENT = "SENT"
    FAILED = "FAILED"


class SocialNotification(Base, GuildScopedMixin, UUIDPrimaryKeyMixin, TimestampMixin):
    """Notificacao manual de conteudo social enviada pelo painel web.

    O mesmo model tambem vira o historico de eventos quando o monitor automatico
    for implementado; por isso URL/plataforma/conteudo ficam separados do envio.
    """

    __tablename__ = "social_notifications"

    creator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger)

    platform: Mapped[SocialPlatform] = mapped_column(
        Enum(SocialPlatform, name="social_platform"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    message_template: Mapped[str] = mapped_column(Text, nullable=False)
    mention_everyone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[SocialNotificationStatus] = mapped_column(
        Enum(SocialNotificationStatus, name="social_notification_status"),
        nullable=False,
        default=SocialNotificationStatus.SENT,
    )
    error_message: Mapped[str | None] = mapped_column(String(1000))
