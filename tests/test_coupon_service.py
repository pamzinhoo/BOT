from __future__ import annotations

import pytest

from database.models.discount_coupon import DiscountCoupon, DiscountType
from services.coupon_service import (
    CouponService,
    InvalidCouponValueError,
    compute_discount,
    format_discount,
    normalize_code,
)
from services.plan_service import render_placeholders


def _coupon(discount_type: DiscountType, value: int) -> DiscountCoupon:
    return DiscountCoupon(
        guild_id=1, code="PROMO", discount_type=discount_type, discount_value=value,
        billing_cycles=[],
    )


def test_normalize_code_is_case_insensitive_and_trimmed() -> None:
    assert normalize_code("  promo10 ") == "PROMO10"


def test_percentage_discount_is_rounded() -> None:
    # 15% de R$ 19,90 = 298,5 centavos -> arredonda pra 299 (round-half-even)
    assert compute_discount(_coupon(DiscountType.PERCENTAGE, 15), 1990) == (298, 1692)


def test_fixed_discount_uses_cents() -> None:
    assert compute_discount(_coupon(DiscountType.FIXED, 500), 1990) == (500, 1490)


def test_discount_bigger_than_price_is_clamped_to_zero() -> None:
    """Desconto maior que o preço nunca gera valor negativo nem erro."""
    assert compute_discount(_coupon(DiscountType.FIXED, 5000), 1990) == (1990, 0)
    assert compute_discount(_coupon(DiscountType.PERCENTAGE, 100), 1990) == (1990, 0)


def test_format_discount() -> None:
    assert format_discount(_coupon(DiscountType.PERCENTAGE, 20)) == "20%"
    assert format_discount(_coupon(DiscountType.FIXED, 500)) == "BRL 5.00"


def test_value_validation_rejects_invalid_values() -> None:
    with pytest.raises(InvalidCouponValueError):
        CouponService._validate_value(DiscountType.PERCENTAGE, 0, allow_zero=False)
    with pytest.raises(InvalidCouponValueError):
        CouponService._validate_value(DiscountType.PERCENTAGE, 101, allow_zero=False)
    with pytest.raises(InvalidCouponValueError):
        CouponService._validate_value(DiscountType.FIXED, -1, allow_zero=True)
    CouponService._validate_value(DiscountType.PERCENTAGE, 100, allow_zero=False)
    CouponService._validate_value(DiscountType.FIXED, 999999, allow_zero=False)


def test_coupon_placeholders_are_rendered() -> None:
    result = render_placeholders(
        "{coupon} {discount} {discount_type} {discount_value} "
        "{original_price} {final_price} {remaining_uses}",
        coupon=_coupon(DiscountType.PERCENTAGE, 20),
        discount_amount=398,
        original_price=1990,
        final_price=1592,
    )

    assert result == "PROMO BRL 3.98 Porcentagem 20 BRL 19.90 BRL 15.92 ∞"


def test_coupon_placeholders_fall_back_without_coupon_context() -> None:
    assert render_placeholders("{coupon} {discount} {remaining_uses}") == "— — —"
