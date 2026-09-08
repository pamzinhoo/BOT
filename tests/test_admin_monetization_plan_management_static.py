from __future__ import annotations

from pathlib import Path


def test_monetization_plan_management_uses_plan_service_safely() -> None:
    source = Path("api/routes/admin/monetization_plans_router.py").read_text(encoding="utf-8")
    init_source = Path("api/routes/admin/__init__.py").read_text(encoding="utf-8")
    schemas = Path("api/schemas/admin.py").read_text(encoding="utf-8")

    assert "monetization_plans_router" in init_source
    assert "router.include_router(monetization_plans_router)" in init_source
    assert '"/guild/{guild_id}/monetization/plans/manage"' in source
    assert '"/guild/{guild_id}/monetization/plans"' in source
    assert '"/guild/{guild_id}/monetization/plans/{plan_id}"' in source
    assert '"/guild/{guild_id}/monetization/plans/{plan_id}/toggle"' in source
    assert "bot.plan_service.create_plan" in source
    assert "bot.plan_service.update_plan" in source
    assert "bot.plan_service.get_plan" in source
    assert "bot.plan_service.list_plans" in source
    assert "delete_plan" not in source
    assert "PaymentHistory" not in source
    assert "Subscription" not in source
    assert "License" not in source
    assert "update_roles" not in source
    assert "remove_roles" not in source
    assert "_role_id" in source
    assert "_price_cents" in source
    assert "Plano ativo precisa ter pelo menos um preco" in source
    assert "refresh_shop_panel" in source
    assert "MonetizationPlanManageRow" in schemas
    assert "MonetizationPlanMutationRequest" in schemas
    assert "MonetizationPlanMutationResponse" in schemas


def test_monetization_plan_management_ui_is_present() -> None:
    page = Path("frontend/src/pages/MonetizationPage.tsx").read_text(encoding="utf-8")
    api = Path("frontend/src/lib/api.ts").read_text(encoding="utf-8")
    css = Path("frontend/src/dashboard-overrides.css").read_text(encoding="utf-8")

    assert "Gerenciar planos" in page
    assert "Novo plano" in page
    assert "Criar plano" in page
    assert "Editar" in page
    assert "Desativar" in page
    assert "Ativo na loja" in page
    assert "monetization/plans/manage" in page
    assert "monetization/plans/${id}" in page
    assert "monetization/plans/${plan.id}/toggle" in page
    assert "MonetizationPlanManageRow" in api
    assert "MonetizationPlanListPayload" in api
    assert "MonetizationPlanMutationPayload" in api
    assert "plan-manage-grid" in css
    assert "plan-create-form" in css
    assert "checkbox-label" in css
