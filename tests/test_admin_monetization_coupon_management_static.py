from pathlib import Path


def test_monetization_coupon_management_uses_coupon_service_safely() -> None:
    source = Path("api/routes/admin/monetization_coupons_router.py").read_text(encoding="utf-8")
    init_source = Path("api/routes/admin/__init__.py").read_text(encoding="utf-8")
    schemas = Path("api/schemas/admin.py").read_text(encoding="utf-8")

    assert "monetization_coupons_router" in init_source
    assert "router.include_router(monetization_coupons_router)" in init_source
    assert '"/guild/{guild_id}/monetization/coupons/manage"' in source
    assert '"/guild/{guild_id}/monetization/coupons"' in source
    assert '"/guild/{guild_id}/monetization/coupons/{coupon_id}"' in source
    assert '"/guild/{guild_id}/monetization/coupons/{coupon_id}/toggle"' in source
    assert "bot.coupon_service.create_coupon" in source
    assert "bot.coupon_service.update_coupon" in source
    assert "bot.coupon_service.set_active" in source
    assert "bot.coupon_service.set_allowed_plans" in source
    assert "bot.coupon_service.list_coupons" in source
    assert "delete_coupon" not in source
    assert "PaymentHistory" not in source
    assert "License" not in source
    assert "add_roles" not in source
    assert "remove_roles" not in source
    assert "MonetizationCouponManageRow" in schemas
    assert "MonetizationCouponListResponse" in schemas
    assert "MonetizationCouponMutationRequest" in schemas
    assert "MonetizationCouponMutationResponse" in schemas


def test_monetization_coupon_management_frontend_is_registered() -> None:
    page = Path("frontend/src/pages/MonetizationPage.tsx").read_text(encoding="utf-8")
    component = Path("frontend/src/components/MonetizationCouponManager.tsx").read_text(encoding="utf-8")
    api = Path("frontend/src/lib/api.ts").read_text(encoding="utf-8")

    assert "MonetizationCouponManager" in page
    assert "Fase 3.3" in page
    assert "Gerenciar cupons" in component
    assert "Novo cupom" in component
    assert "Criar cupom" in component
    assert "Desativar" in component
    assert "Ativar" in component
    assert "monetization/coupons/manage" in component
    assert "monetization/coupons/${id}" in component
    assert "monetization/coupons/${coupon.id}/toggle" in component
    assert "MonetizationCouponListPayload" in api
    assert "MonetizationCouponMutationPayload" in api
    assert "MonetizationCouponMutationResponse" in api
