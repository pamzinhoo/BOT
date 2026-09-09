from pathlib import Path

MONETIZATION_BACKEND_FILES = [
    Path("api/routes/admin/monetization_router.py"),
    Path("api/routes/admin/monetization_plans_router.py"),
    Path("api/routes/admin/monetization_coupons_router.py"),
    Path("api/routes/admin/monetization_settings_router.py"),
]

MONETIZATION_FRONTEND_FILES = [
    Path("frontend/src/pages/MonetizationPage.tsx"),
    Path("frontend/src/components/MonetizationCouponManager.tsx"),
    Path("frontend/src/components/MonetizationPaymentSettings.tsx"),
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_phase3_review_document_exists() -> None:
    doc = _read(Path("docs/DASHBOARD_MONETIZATION_PHASE3_REVIEW.md"))

    assert "Fase 3.1 — Analytics de monetização" in doc
    assert "Fase 3.2 — Gerenciar planos" in doc
    assert "Fase 3.3 — Gerenciar cupons" in doc
    assert "Fase 3.4 — Configurações da loja/pagamento" in doc
    assert "Checklist de validação local" in doc
    assert "Painel web" in doc
    assert "não edita `.env`" in doc
    assert "não adiciona/remove cargos" in doc


def test_phase3_routes_are_registered() -> None:
    init_source = _read(Path("api/routes/admin/__init__.py"))

    assert "monetization_router" in init_source
    assert "monetization_plans_router" in init_source
    assert "monetization_coupons_router" in init_source
    assert "monetization_settings_router" in init_source
    assert "router.include_router(monetization_router)" in init_source
    assert "router.include_router(monetization_plans_router)" in init_source
    assert "router.include_router(monetization_coupons_router)" in init_source
    assert "router.include_router(monetization_settings_router)" in init_source


def test_phase3_frontend_sections_are_visible() -> None:
    page = _read(Path("frontend/src/pages/MonetizationPage.tsx"))
    coupons = _read(Path("frontend/src/components/MonetizationCouponManager.tsx"))
    settings = _read(Path("frontend/src/components/MonetizationPaymentSettings.tsx"))

    assert "Fase 3.1" in page
    assert "Fase 3.2" in page
    assert "Fase 3.3" in page
    assert "Fase 3.4" in page
    assert "Analytics de vendas" in page
    assert "Gerenciar planos" in page
    assert "Gerenciar cupons" in coupons
    assert "Configurações da loja/pagamento" in settings
    assert "Planos e desempenho" in page


def test_phase3_write_routes_use_services_and_keep_executor() -> None:
    plans = _read(Path("api/routes/admin/monetization_plans_router.py"))
    coupons = _read(Path("api/routes/admin/monetization_coupons_router.py"))
    settings = _read(Path("api/routes/admin/monetization_settings_router.py"))

    assert "bot.plan_service.create_plan" in plans
    assert "bot.plan_service.update_plan" in plans
    assert "bot.coupon_service.create_coupon" in coupons
    assert "bot.coupon_service.update_coupon" in coupons
    assert "bot.coupon_service.set_active" in coupons
    assert "_DASHBOARD_EXECUTOR" in coupons
    assert "Painel web" in coupons
    assert "publish_shop_panel" in settings
    assert "refresh_shop_panel" in settings
    assert "record_config_change" in settings


def test_phase3_final_safety_forbidden_backend_operations() -> None:
    forbidden_by_file = {
        "api/routes/admin/monetization_plans_router.py": [
            "delete_plan",
            "PaymentHistory",
            "Subscription",
            "License",
            "add_roles",
            "remove_roles",
        ],
        "api/routes/admin/monetization_coupons_router.py": [
            "delete_coupon",
            "PaymentHistory",
            "Subscription",
            "License",
            "add_roles",
            "remove_roles",
        ],
        "api/routes/admin/monetization_settings_router.py": [
            "PaymentHistory",
            "Subscription",
            "License",
            "Product",
            "add_roles",
            "remove_roles",
            "mercadopago_access_token =",
            "mercadopago_public_key =",
            "mercadopago_webhook_secret =",
        ],
    }

    for filename, forbidden_terms in forbidden_by_file.items():
        source = _read(Path(filename))
        for term in forbidden_terms:
            assert term not in source


def test_phase3_final_frontend_does_not_show_sensitive_gateway_fields() -> None:
    combined = "\n".join(_read(path) for path in MONETIZATION_FRONTEND_FILES)

    assert "QRCode" not in combined
    assert "access_token" not in combined
    assert "webhook_secret" not in combined
    assert "public_key" not in combined
    assert "checkout_url" not in combined
    assert "Chaves ficam somente no .env" in combined
