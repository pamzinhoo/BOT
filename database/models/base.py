from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base declarativa compartilhada por todos os models do bot."""


class UUIDPrimaryKeyMixin:
    """PK UUID para tabelas internas (claims, avaliacoes, logs, etc.).

    IDs do Discord (guild/canal/usuario/mensagem) NAO usam este mixin: eles sao
    armazenados como BigInteger nas colunas correspondentes, pois ja chegam
    como snowflakes inteiros da API do Discord.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    """Adiciona created_at/updated_at com timezone UTC a um model."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
