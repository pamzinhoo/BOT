from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Player(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Conta interna do ecossistema Launcher/Jogo/Licenciamento — 1 linha por
    Discord ID vinculado. E o `player_id` que Device/License/Download usam
    daqui pra frente; nenhuma dessas tabelas guarda discord_id diretamente,
    pra nunca depender do Discord como autoridade de licenca (Discord e so
    provedor de identidade no login, ver docs/LIMERENCE_LAUNCHER_ARCHITECTURE.md).

    Sem guild_id: ao contrario do resto do bot (multi-tenant por servidor),
    o ecossistema do jogo e uma unica comunidade/produto — Player e global.
    """

    __tablename__ = "players"

    discord_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True, index=True)
    discord_username: Mapped[str | None] = mapped_column(String(64))

    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_ip: Mapped[str | None] = mapped_column(INET)

    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    banned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    banned_reason: Mapped[str | None] = mapped_column(String(200))
