from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Partnership(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """1 linha por parceiro/streamer de uma guild — o espaco permanente dele
    (canal ou topico de forum) e a ultima divulgacao publicada. Tabela propria,
    isolada de tickets/pagamentos. Uma unica linha ativa por (guild_id,
    owner_id): nunca cria canal/topico duplicado pro mesmo parceiro."""

    __tablename__ = "partnerships"
    __table_args__ = (
        UniqueConstraint("guild_id", "owner_id", name="uq_partnerships_guild_owner"),
        Index("ix_partnerships_guild_id", "guild_id"),
    )

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # cargo dedicado desse parceiro (ex.: @Front Design), criado junto com o
    # canal no modo Canal — modo Forum nao suporta overwrite por topico, entao
    # fica None nesse caso (limitacao da API do Discord pra threads).
    role_id: Mapped[int | None] = mapped_column(BigInteger)
    channel_id: Mapped[int | None] = mapped_column(BigInteger)
    thread_id: Mapped[int | None] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(BigInteger)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    invite: Mapped[str | None] = mapped_column(String(200))
    banner: Mapped[str | None] = mapped_column(String(500))
    category_label: Mapped[str | None] = mapped_column(String(100))

    last_publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
