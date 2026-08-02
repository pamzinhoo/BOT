from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, text
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
    """Adiciona created_at/updated_at com timezone UTC a um model.

    Alguns models antigos de settings (*_settings) tem so updated_at, sem
    created_at — debito conhecido, nao retrofitado pra evitar migracao em
    massa sem bug associado. Todo model novo tem que usar este mixin inteiro,
    nunca declarar updated_at a mao.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class GuildScopedMixin:
    """Convencao pra models novos com escopo por guild.

    guild_id fica cru (BigInteger), sem FK real pra `guilds` — a tabela
    `guilds` (database/models/guild.py) e populada de forma lazy via
    GuildService.ensure_guild e serve hoje so como registro de tenant, nao
    como referencia obrigatoria (as ~20 tabelas anteriores a este mixin
    tambem guardam guild_id cru, sem FK). Todo repository de um model que usa
    este mixin tem que expor list_by_guild(guild_id) proprio — nunca usar
    BaseRepository.list_all() sem filtro (ver aviso em base_repository.py).
    """

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
