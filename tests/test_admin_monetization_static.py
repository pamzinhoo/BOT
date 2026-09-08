from __future__ import annotations

from pathlib import Path


def test_dashboard_monetization_router_is_read_only_summary() -> None:
    source = Path("api/routes/admin/monetization_router.py").read_text(encoding="utf-8")
    schemas = Path("api/schemas/admin.py").read_text(encoding="utf-8")

    assert '"/guild/{guild_id}/monetization/summary"' in source
    assert "response_model=MonetizationSummaryResponse" in source
    assert "PaymentHistory" in source
    assert "Plan" in source
    assert "DiscountCoupon" in source
    assert "Subscription" in source
    assert "Product" in source
    assert "MonetizationSettings" in source
    assert "somente leitura" in source
    assert "nao expõe QR code PIX" in source
    assert "Products sao globais" in source
    assert "required_role_guild_id == guild_id" in source
    assert "Product.id.in_(plan_product_ids)" in source
    recent_payment_schema = schemas.split("class MonetizationRecentPayment", 1)[1].split("class MonetizationPlanRow", 1)[0]
    assert "pix_qr_code" not in recent_payment_schema
    assert "checkout_url" not in recent_payment_schema
    assert "payer_information" not in recent_payment_schema
    assert "external_id" not in recent_payment_schema
    assert "MonetizationSummaryResponse" in schemas
    assert "MonetizationRecentPayment" in schemas
    assert "MonetizationAlert" in schemas


def test_dashboard_monetization_page_is_registered_and_safe() -> None:
    init_source = Path("api/routes/admin/__init__.py").read_text(encoding="utf-8")
    app = Path("frontend/src/App.tsx").read_text(encoding="utf-8")
    shell = Path("frontend/src/components/AppShell.tsx").read_text(encoding="utf-8")
    page = Path("frontend/src/pages/MonetizationPage.tsx").read_text(encoding="utf-8")
    api = Path("frontend/src/lib/api.ts").read_text(encoding="utf-8")
    events = Path("api/routes/admin/events_router.py").read_text(encoding="utf-8")

    assert "monetization_router" in init_source
    assert "router.include_router(monetization_router)" in init_source
    assert '<Route path="/monetization" element={<MonetizationPage />} />' in app
    assert '{ label: "Monetização", to: "/monetization"' in shell
    assert "monetization" in events
    assert "MonetizationSummary" in api
    assert "Fase 3.1" in page
    assert "somente leitura" in page
    assert "não exibe QR Code PIX" in page
    assert "Pagamentos recentes" in page
    assert "security_notes" in page


def test_dashboard_monetization_analytics_explains_sources() -> None:
    source = Path("api/routes/admin/monetization_router.py").read_text(encoding="utf-8")
    schemas = Path("api/schemas/admin.py").read_text(encoding="utf-8")
    page = Path("frontend/src/pages/MonetizationPage.tsx").read_text(encoding="utf-8")
    api = Path("frontend/src/lib/api.ts").read_text(encoding="utf-8")
    css = Path("frontend/src/dashboard-overrides.css").read_text(encoding="utf-8")

    assert "MonetizationPlanRow" in schemas
    assert "MonetizationStatusBreakdown" in schemas
    assert "MonetizationCouponRow" in schemas
    assert "plans: list[MonetizationPlanRow]" in schemas
    assert "payment_status_breakdown" in schemas
    assert "source_notes" in schemas
    assert "analytics" in schemas
    assert "payment_plan_rows" in source
    assert "top_seller_plan" in source
    assert "top_revenue_plan" in source
    assert "Receita aprovada registrada" in source
    assert "nao prova sozinha que foi venda real" in source
    assert "5 planos no total" in source
    assert "1 cupom no total" in source
    assert "MonetizationPlanRow" in api
    assert "MonetizationStatusBreakdown" in api
    assert "MonetizationCouponRow" in api
    assert "Analytics de vendas" in page
    assert "Planos e desempenho" in page
    assert "De onde vêm esses números" in page
    assert "Cupons cadastrados" in page
    assert "analytics-grid" in css
    assert "source-note-grid" in css
