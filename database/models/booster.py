from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Booster(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """1 linha por (guild, usuario) que ja impulsionou o servidor alguma vez.
    boost_count incrementa toda vez que o usuario reinicia o boost apos te-lo
    removido — usado futuramente pro Hall dos Boosters/ranking/estatisticas."""

    __tablename__ = "boosters"
    __table_args__ = (UniqueConstraint("guild_id", "user_id", name="uq_boosters_guild_user"),)

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    boost_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    boost_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currently_boosting: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_removed: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
