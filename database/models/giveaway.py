from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import UniqueConstraint

from database.models.base import Base, GuildScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class GiveawayStatus(enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELED = "CANCELED"


class GiveawayPrizeType(enum.Enum):
    ROLE = "ROLE"
    CUSTOM = "CUSTOM"


class Giveaway(Base, GuildScopedMixin, UUIDPrimaryKeyMixin, TimestampMixin):
    """Sorteio criado via painel /config -> Comunidade -> Sorteios. Canal e
    escolhido pelo staff no momento do envio (nao ha canal fixo em settings,
    diferente de Verificacao) — varios sorteios podem estar abertos ao mesmo
    tempo, cada um com seu proprio painel fixo."""

    __tablename__ = "giveaways"

    creator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    prize_type: Mapped[GiveawayPrizeType] = mapped_column(
        Enum(GiveawayPrizeType, name="giveaway_prize_type"), nullable=False, default=GiveawayPrizeType.CUSTOM
    )
    prize_role_id: Mapped[int | None] = mapped_column(BigInteger)
    prize_text: Mapped[str | None] = mapped_column(String(500))
    allowed_role_ids: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    winners_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[GiveawayStatus] = mapped_column(
        Enum(GiveawayStatus, name="giveaway_status"), nullable=False, default=GiveawayStatus.OPEN
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GiveawayEntry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """1 participacao por usuario por sorteio — garantido pela UniqueConstraint
    no banco (mesmo padrao de PollVote), seguro contra clique duplo no botao
    Participar."""

    __tablename__ = "giveaway_entries"
    __table_args__ = (UniqueConstraint("giveaway_id", "user_id", name="uq_giveaway_entry_one_per_user"),)

    giveaway_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("giveaways.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # peso de voto do membro no momento da participacao (mesmo VoteWeight usado
    # nas enquetes, resolvido por cargo VIP) — snapshot pra nao mudar o sorteio
    # ja em andamento se o cargo/peso mudar depois. Default 1 = sem peso extra.
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class GiveawayWinner(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Historico append-only de vencedores. Sorteio novo (reroll) so adiciona
    linhas — nunca apaga as anteriores, entao um mesmo user_id pode aparecer
    mais de uma vez se for sorteado de novo em outra rodada."""

    __tablename__ = "giveaway_winners"

    giveaway_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("giveaways.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
