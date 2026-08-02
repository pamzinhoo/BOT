from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, UUIDPrimaryKeyMixin


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DiscountCouponRedemption(Base, UUIDPrimaryKeyMixin):
    """1 linha por uso efetivo de um cupom (cobranca gerada com desconto).

    Historico NUNCA e apagado: a FK pro cupom e RESTRICT de proposito, entao
    excluir um cupom com resgates e impossivel fisicamente — o CouponService
    converte esse caso em soft-delete (active=False + deleted_at).

    `guild_id`/`user_id` sao desnormalizados aqui pra que o relatorio de
    receita continue de pe mesmo que o cupom mude de escopo ou o pagamento
    suma. `payment_id` e nullable (SET NULL) porque o resgate e gravado logo
    apos a cobranca, mas o historico de uso vale mesmo sem ela."""

    __tablename__ = "discount_coupon_redemptions"

    coupon_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("discount_coupons.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payment_history.id", ondelete="SET NULL")
    )

    original_price: Mapped[int] = mapped_column(Integer, nullable=False)  # centavos
    discount_amount: Mapped[int] = mapped_column(Integer, nullable=False)  # centavos
    final_price: Mapped[int] = mapped_column(Integer, nullable=False)  # centavos

    redeemed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
