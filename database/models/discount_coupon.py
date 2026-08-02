from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DiscountType(enum.Enum):
    """PERCENTAGE -> discount_value e um inteiro de 1 a 100 (por cento).
    FIXED -> discount_value e um valor em CENTAVOS, igual a todo campo de
    dinheiro do projeto (ver Plan.price_monthly)."""

    PERCENTAGE = "percentage"
    FIXED = "fixed"


class DiscountCoupon(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Cupom de desconto criado por um admin via /config painel > Monetizacao >
    Cupons. Nada aqui e fixo: codigo, valor, planos, ciclos, limites e validade
    sao 100% definidos pela guild.

    Convencoes importantes (nenhuma delas e obvia pelo schema):

    * `code` e guardado SEMPRE em MAIUSCULAS (normalizado no CouponService) e
      comparado em maiusculas. E o "Nome do cupom" da UI. A unicidade
      (guild_id, code) portanto ja e case-insensitive na pratica, sem precisar
      de indice funcional.
    * `guild_id` cru, sem FK — mesma convencao das outras ~20 tabelas
      multi-tenant. TODA query filtra por guild_id: um cupom de uma guild nunca
      pode ser resolvido a partir de outra.
    * `starts_at`/`expires_at` NULL de um lado = sem restricao daquele lado.
    * `max_global_uses`/`max_uses_per_user` NULL = ilimitado (∞ na UI).
    * `billing_cycles` = lista de BillingCycle.value ("monthly"/"yearly"/
      "one_time"). Lista vazia ou NULL = vale pra todos os ciclos.
    * Planos validos NAO ficam aqui: ver discount_coupon_plans (0 linhas =
      vale pra todos os planos).
    * Exclusao e SOFT (active=False + deleted_at) quando o cupom ja tem
      resgates — o historico de uso nunca pode ser apagado (FK RESTRICT em
      discount_coupon_redemptions).
    """

    __tablename__ = "discount_coupons"
    __table_args__ = (UniqueConstraint("guild_id", "code", name="uq_discount_coupons_guild_code"),)

    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    emoji: Mapped[str | None] = mapped_column(String(64))

    discount_type: Mapped[DiscountType] = mapped_column(
        Enum(DiscountType, name="discount_coupon_type"),
        nullable=False,
        default=DiscountType.PERCENTAGE,
    )
    discount_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    max_global_uses: Mapped[int | None] = mapped_column(Integer)
    max_uses_per_user: Mapped[int | None] = mapped_column(Integer)

    required_role_id: Mapped[int | None] = mapped_column(BigInteger)
    allow_stack: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    billing_cycles: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
