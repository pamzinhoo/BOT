from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EnqueteSettings(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """1 linha por guild — configuracao do sistema de Enquetes (/config ->
    Enquetes). Mensagens ficam None ate a staff personalizar; nesse caso o
    servico usa um texto padrao com os placeholders {title} {creator}
    {winner} {votes} {participants}, renderizados via render_placeholders."""

    __tablename__ = "enquete_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    default_weight_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="SNAPSHOT")
    creation_message: Mapped[str | None] = mapped_column(Text)
    closing_message: Mapped[str | None] = mapped_column(Text)
    result_message: Mapped[str | None] = mapped_column(Text)
