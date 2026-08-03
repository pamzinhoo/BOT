from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Plan(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Plano de apoio financeiro configurado por uma guild. Nada aqui e fixo —
    nome/emoji/cor/preco/cargo/beneficios/mensagens sao todos definidos pelo
    administrador via painel de config (Monetizacao). O bot nunca assume um
    plano especifico, apenas opera sobre o que a guild cadastrar."""

    __tablename__ = "plans"
    __table_args__ = (UniqueConstraint("guild_id", "name", name="uq_plans_guild_name"),)

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    emoji: Mapped[str | None] = mapped_column(String(64))
    color: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)

    price_monthly: Mapped[int | None] = mapped_column(Integer)  # centavos
    price_yearly: Mapped[int | None] = mapped_column(Integer)
    price_one_time: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="BRL")

    role_id: Mapped[int | None] = mapped_column(BigInteger)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
