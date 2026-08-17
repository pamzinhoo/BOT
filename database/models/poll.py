from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, GuildScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class PollStatus(enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELED = "CANCELED"


class PollVisibility(enum.Enum):
    PUBLIC = "PUBLIC"
    ROLE_RESTRICTED = "ROLE_RESTRICTED"
    PREMIUM = "PREMIUM"


class Poll(Base, GuildScopedMixin, UUIDPrimaryKeyMixin, TimestampMixin):
    """Enquete criada por uma guild via /enquete criar. weight_mode e copiado
    do default da guild (EnqueteSettings) no momento da criacao — mudar o
    default depois nao altera enquetes ja abertas."""

    __tablename__ = "polls"

    creator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[PollStatus] = mapped_column(
        Enum(PollStatus, name="poll_status"), nullable=False, default=PollStatus.OPEN
    )
    visibility: Mapped[PollVisibility] = mapped_column(
        Enum(PollVisibility, name="poll_visibility"), nullable=False, default=PollVisibility.PUBLIC
    )
    required_role_id: Mapped[int | None] = mapped_column(BigInteger)
    required_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("plans.id", ondelete="SET NULL")
    )
    weight_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="SNAPSHOT")
    # thumbnail exibida no embed da enquete (logo/imagem do tema) — URL colada
    # pelo staff na criacao, nunca upload direto (Modal do Discord nao aceita
    # arquivo).
    image_url: Mapped[str | None] = mapped_column(String(500))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PollOption(Base, UUIDPrimaryKeyMixin):
    """Opcao de voto. Sem coluna de contagem — total ponderado e calculado em
    runtime via SUM(poll_votes.weight) GROUP BY option_id, evitando drift
    entre um contador e as linhas reais de voto."""

    __tablename__ = "poll_options"

    poll_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("polls.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # emoji custom por opcao (aparece no embed e no botao) — None usa um
    # marcador padrao derivado de button_style (ver utils/poll_style.py).
    emoji: Mapped[str | None] = mapped_column(String(64))
    # um dos 4 estilos REAIS de botao do Discord (nao aceita hex arbitrario,
    # limitacao da propria API): success/danger/primary/secondary.
    button_style: Mapped[str] = mapped_column(String(20), nullable=False, default="secondary")


class PollVote(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """1 voto por usuario por enquete — garantido pela UniqueConstraint no
    banco (nao so checagem em service), pra ser seguro contra cliques
    concorrentes no botao de voto. weight e o peso no momento do voto."""

    __tablename__ = "poll_votes"
    __table_args__ = (UniqueConstraint("poll_id", "user_id", name="uq_poll_vote_one_per_user"),)

    poll_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("polls.id", ondelete="CASCADE"), nullable=False)
    option_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("poll_options.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class VoteWeight(Base, GuildScopedMixin, UUIDPrimaryKeyMixin, TimestampMixin):
    """Peso de voto por cargo, por guild. source="PLAN_BENEFIT" + source_plan_id
    marca linhas geradas automaticamente por um plano (peso de votacao como
    beneficio) — nesse caso o plan_benefit.py continua livre-texto, intocado;
    o vinculo estruturado vive so aqui."""

    __tablename__ = "vote_weights"
    __table_args__ = (UniqueConstraint("guild_id", "role_id", name="uq_vote_weight_guild_role"),)

    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="MANUAL")
    source_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("plans.id", ondelete="SET NULL")
    )
