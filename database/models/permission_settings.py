from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin

# Nomes das 8 acoes controlaveis. Lista vazia numa coluna = cai no
# comportamento legado daquela acao (ver utils/checks.py:member_can).
PERMISSION_ACTIONS: list[str] = [
    "claim",
    "unclaim",
    "fechar",
    "reabrir",
    "excluir",
    "auditoria",
    "ranking",
    "config",
    "recurso_banimento",
    "analises",
    "convite",
]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _empty_list() -> list[int]:
    return []


class PermissionSettings(Base, UUIDPrimaryKeyMixin):
    """1 linha por guild — quais cargos podem executar cada acao. Cada coluna
    e uma lista de role_id (JSONB); vazia = usa o fallback padrao do bot."""

    __tablename__ = "permission_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    claim: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=_empty_list)
    unclaim: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=_empty_list)
    fechar: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=_empty_list)
    reabrir: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=_empty_list)
    excluir: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=_empty_list)
    auditoria: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=_empty_list)
    ranking: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=_empty_list)
    config: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=_empty_list)
    recurso_banimento: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=_empty_list)
    analises: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=_empty_list)
    convite: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=_empty_list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
