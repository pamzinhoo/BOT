from __future__ import annotations

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CommandHelp(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """1 linha por comando cadastrado no /help. Novos comandos entram so com um
    INSERT nessa tabela — o cog/service de ajuda nao precisa mudar."""

    __tablename__ = "command_help"

    command_name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    usage: Mapped[str] = mapped_column(String(255), nullable=False)
    examples: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # "public" | "staff" | "admin" — controla quem ve o comando no /help (Etapa 13)
    required_permission: Mapped[str] = mapped_column(String(16), nullable=False, default="public")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
