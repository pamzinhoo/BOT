from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Partnership(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """1 linha por parceiro/streamer de uma guild — so o registro do canal
    dele (criado automaticamente via on_member_update). Nao guarda mais nome/
    descricao/divulgacao: tudo isso agora e feito manualmente pelo proprio
    parceiro dentro do canal. Uma unica linha ativa por (guild_id, owner_id):
    nunca cria canal duplicado pro mesmo parceiro."""

    __tablename__ = "partnerships"
    __table_args__ = (
        UniqueConstraint("guild_id", "owner_id", name="uq_partnerships_guild_owner"),
        Index("ix_partnerships_guild_id", "guild_id"),
        Index(
            "ix_partnerships_guild_announce",
            "guild_id", "last_announced_at",
            postgresql_where=text("archived_at IS NULL"),
        ),
    )

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[int | None] = mapped_column(BigInteger)
    # cargo dedicado desse parceiro (ex.: @Front Design), criado junto com o
    # canal — best-effort, fica None se a criacao/atribuicao falhar.
    role_id: Mapped[int | None] = mapped_column(BigInteger)

    # preenchido quando o canal foi movido pra categoria "Parceiros Antigos"
    # (perdeu o cargo) — fonte de verdade pra saber se deve restaurar ou criar
    # canal novo quando o cargo volta.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ultima vez que esse parceiro foi citado na divulgacao automatica —
    # usado pro rodizio (sempre anuncia quem tem o valor mais antigo/nulo).
    last_announced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
