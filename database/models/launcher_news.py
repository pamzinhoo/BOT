from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class LauncherNews(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Item de novidade exibido na tela inicial do Launcher. Exclusao e SOFT
    (`deleted_at`), mesmo padrao de DiscountCoupon — nao ha motivo pra perder
    o historico do que ja foi publicado."""

    __tablename__ = "launcher_news"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    cover_image_url: Mapped[str | None] = mapped_column(String(500))

    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_by_staff_id: Mapped[int | None] = mapped_column(BigInteger)
    published_by_staff_id: Mapped[int | None] = mapped_column(BigInteger)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
