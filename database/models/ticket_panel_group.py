from __future__ import annotations

from sqlalchemy import BigInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

MAX_GROUP_PANELS = 5


def _empty_list() -> list[str]:
    return []


class TicketPanelGroup(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """1 linha por publicacao combinada de varios `TicketPanel` numa unica
    mensagem — a embed (titulo/descricao/banner/thumb/cor) vem do painel
    principal (primeiro id de `panel_ids`), e cada painel listado vira um
    botao na mesma view (ex.: "Suporte" + "Denuncia" lado a lado).

    Nao duplica config nenhuma: so referencia paineis ja existentes em
    `ticket_panels`. Editar um painel (embed/botao/comportamento) reflete
    automaticamente aqui, igual reflete na publicacao individual dele."""

    __tablename__ = "ticket_panel_groups"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # ordenado: panel_ids[0] e o principal (define a embed), o resto so contribui botao
    panel_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=_empty_list)

    channel_id: Mapped[int | None] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
