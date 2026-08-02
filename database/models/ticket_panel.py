from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


def _empty_list() -> list[int]:
    return []


class TicketPanel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """1 linha por painel de abertura de tickets configurado por uma guild.

    Nada aqui e fixo: nome/embed/botao/comportamento/formulario/aprovacao sao
    todos definidos pelo administrador via /config -> Tickets -> Paineis. Uma
    guild pode ter quantos paineis quiser (Suporte, Compras, Denuncias, ...),
    cada um com seu proprio canal, categoria, cargos e regras.

    Este model NAO substitui `ticket_settings` (1 linha por guild, comportamento
    global + kill switch do sistema inteiro) nem o painel legado com dropdown de
    categoria (views/painel_view.py) — ele fica por cima da mesma infra de
    tickets (TicketService.create_ticket, TicketActionsView, transcricao, stats).
    """

    __tablename__ = "ticket_panels"
    __table_args__ = (UniqueConstraint("guild_id", "key", name="uq_ticket_panels_guild_key"),)

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    # slug estavel derivado do nome — entra no custom_id do botao, entao nunca
    # muda depois de criado (renomear o painel nao mexe na key).
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # preenchidos quando o painel e publicado num canal
    channel_id: Mapped[int | None] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(BigInteger)

    # categoria do Discord onde os canais de ticket deste painel sao criados
    ticket_category_id: Mapped[int | None] = mapped_column(BigInteger)
    # cargos que enxergam/atendem os tickets deste painel (overwrites + ping)
    responsible_role_ids: Mapped[list[int]] = mapped_column(
        JSONB, nullable=False, default=_empty_list
    )

    embed_title: Mapped[str | None] = mapped_column(String(256))
    embed_description: Mapped[str | None] = mapped_column(Text)
    embed_color: Mapped[int | None] = mapped_column(Integer)
    embed_image_url: Mapped[str | None] = mapped_column(Text)
    embed_thumbnail_url: Mapped[str | None] = mapped_column(Text)
    embed_footer: Mapped[str | None] = mapped_column(Text)

    button_label: Mapped[str | None] = mapped_column(String(80))
    button_emoji: Mapped[str | None] = mapped_column(String(64))
    button_style: Mapped[str] = mapped_column(String(16), nullable=False, default="primary")

    # comportamento — quando nulo, cai no valor global de `ticket_settings`
    max_tickets_per_user: Mapped[int | None] = mapped_column(Integer)
    allow_multiple_tickets: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    auto_close_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    delete_delay_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    transcript_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    evaluation_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    dm_on_close_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # restricao EXTRA de quem pode assumir os tickets deste painel: vazio = so a
    # permissao global de `claim` (permission_settings) decide. Nao e um sistema
    # de permissao paralelo — e um filtro aplicado depois do member_can padrao.
    claim_role_ids: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=_empty_list)

    form_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    approval_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approval_granted_role_id: Mapped[int | None] = mapped_column(BigInteger)
