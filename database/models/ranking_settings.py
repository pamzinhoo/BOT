from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


def _utcnow() -> datetime:
    return datetime.now(UTC)


class RankingSettings(Base, UUIDPrimaryKeyMixin):
    """1 linha por guild — criterio e periodo padrao do ranking.

    `criteria`: "tickets" ou "avaliacao". `default_period`: valor de RankingPeriod
    (daily/weekly/monthly/alltime). Strings simples em vez de Enum de banco pra
    evitar mais um tipo Postgres pra essas duas opcoes pequenas.
    """

    __tablename__ = "ranking_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    criteria: Mapped[str] = mapped_column(String(20), nullable=False, default="tickets")
    default_period: Mapped[str] = mapped_column(String(20), nullable=False, default="alltime")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
