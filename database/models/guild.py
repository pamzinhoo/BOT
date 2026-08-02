from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Guild(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Registro de tenant. Populado de forma lazy por GuildService.ensure_guild
    (on_guild_join + varredura no startup) — nao serve de FK pras ~20 tabelas
    que ja guardam guild_id cru, so como fonte de verdade de metadata/ciclo
    de vida do servidor (nome, dono, ativo ou nao)."""

    __tablename__ = "guilds"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
