from __future__ import annotations

from pathlib import Path


def test_dashboard_settings_router_uses_namespaced_keys() -> None:
    source = Path("api/routes/admin/settings_router.py").read_text(encoding="utf-8")

    assert 'f"{category_key}.{field.attr}"' in source
    assert 'grouped.setdefault(entry.updater, {})[entry.field.attr]' in source
    assert "Configuracao desconhecida ou ambigua." in source


def test_dashboard_settings_router_preserves_bool_values() -> None:
    source = Path("api/routes/admin/settings_router.py").read_text(encoding="utf-8")
    serialize_index = source.index("def _serialize_value")
    bool_index = source.index("isinstance(raw, bool)", serialize_index)
    int_index = source.index("isinstance(raw, int)", serialize_index)

    assert bool_index < int_index
    assert "bool herda de int" in source


def test_dashboard_settings_router_validates_discord_references() -> None:
    source = Path("api/routes/admin/settings_router.py").read_text(encoding="utf-8")

    assert "def _validate_reference" in source
    assert "Canal nao encontrado neste servidor." in source
    assert "Cargo nao encontrado ou invalido neste servidor." in source
    assert '"missing_reference": True' in source


def test_dashboard_events_router_is_registered_before_legacy_router() -> None:
    source = Path("api/routes/admin/__init__.py").read_text(encoding="utf-8")

    assert "events_router" in source
    assert "settings_router" in source
    assert "giveaways_router" in source
    assert "legacy_router" in source
    assert source.index("router.include_router(settings_router)") < source.index("router.include_router(events_router)")
    assert source.index("router.include_router(events_router)") < source.index("router.include_router(giveaways_router)")
    assert source.index("router.include_router(giveaways_router)") < source.index("router.include_router(legacy_router)")


def test_dashboard_events_router_pushes_invalidation_events() -> None:
    source = Path("api/routes/admin/events_router.py").read_text(encoding="utf-8")

    assert "text/event-stream" in source
    assert "dashboard.invalidate" in source
    assert "settings" in source
    assert "discord-options" in source
    assert "dlcs" in source
    assert "giveaways" in source


def test_dashboard_giveaways_use_existing_service_and_discord_view() -> None:
    source = Path("api/routes/admin/giveaways_router.py").read_text(encoding="utf-8")
    service = Path("services/giveaway_service.py").read_text(encoding="utf-8")
    app = Path("frontend/src/App.tsx").read_text(encoding="utf-8")
    shell = Path("frontend/src/components/AppShell.tsx").read_text(encoding="utf-8")
    page = Path("frontend/src/pages/GiveawaysPage.tsx").read_text(encoding="utf-8")
    css = Path("frontend/src/dashboard-overrides.css").read_text(encoding="utf-8")

    assert "bot.giveaway_service.create_giveaway" in source
    assert "GiveawayOpenView" in source
    assert "close_and_announce" in source
    assert "cancel_giveaway" in source
    assert "SORTEIO_CRIADO_PAINEL_WEB" in source
    assert "executor_name=_DASHBOARD_ACTOR" in source
    assert "duration_amount" in source
    assert "duration_unit" in source
    assert "async def cancel_giveaway" in service
    assert '<Route path="/giveaways" element={<GiveawaysPage />} />' in app
    assert '{ label: "Sorteios", to: "/giveaways"' in shell
    assert "role-checkbox" in page
    assert "toggleAllowedRole" in page
    assert "role-checkbox-grid" in css
