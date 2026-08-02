from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


class DiscountCouponPlan(Base, UUIDPrimaryKeyMixin):
    """Associacao cupom <-> plano.

    CONVENCAO (importante): ZERO linhas para um cupom significa "Todos os
    planos". Nao existe linha-sentinela de "todos" — a ausencia de restricao E
    a ausencia de linhas. Quem valida isso e o CouponService; nenhuma View
    pode reimplementar essa regra.

    Os dois lados sao CASCADE: apagar o plano ou o cupom so apaga a restricao,
    nunca o historico de resgates (esse fica em discount_coupon_redemptions,
    com FK RESTRICT)."""

    __tablename__ = "discount_coupon_plans"
    __table_args__ = (
        UniqueConstraint("coupon_id", "plan_id", name="uq_discount_coupon_plan"),
    )

    coupon_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("discount_coupons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
