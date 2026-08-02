from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PaymentDmSettings(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """1 linha por guild — embed enviado por DM ao comprador quando um staff
    aprova ou rejeita um pagamento. Cada estado (aprovado/rejeitado) tem seu
    proprio titulo/descricao/cor/rodape/imagem/thumbnail, editaveis pelo
    /config painel. Campo vazio cai no texto padrao (ver services/plan_service
    render_placeholders + views/embeds.payment_dm_embed)."""

    __tablename__ = "payment_dm_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)

    approved_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    approved_embed_title: Mapped[str | None] = mapped_column(String(256))
    approved_embed_description: Mapped[str | None] = mapped_column(Text)
    approved_embed_color: Mapped[int | None] = mapped_column(Integer)
    approved_embed_footer: Mapped[str | None] = mapped_column(Text)
    approved_embed_thumbnail_url: Mapped[str | None] = mapped_column(Text)
    approved_embed_image_url: Mapped[str | None] = mapped_column(Text)

    rejected_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rejected_embed_title: Mapped[str | None] = mapped_column(String(256))
    rejected_embed_description: Mapped[str | None] = mapped_column(Text)
    rejected_embed_color: Mapped[int | None] = mapped_column(Integer)
    rejected_embed_footer: Mapped[str | None] = mapped_column(Text)
    rejected_embed_thumbnail_url: Mapped[str | None] = mapped_column(Text)
    rejected_embed_image_url: Mapped[str | None] = mapped_column(Text)
