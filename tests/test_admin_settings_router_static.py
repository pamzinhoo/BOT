from __future__ import annotations

from pathlib import Path


def test_dashboard_settings_router_uses_namespaced_keys() -> None:
    source = Path("api/routes/admin/settings_router.py").read_text(encoding="utf-8")

    assert 'f"{category_key}.{field.attr}"' in source
    assert 'grouped.setdefault(entry.updater, {})[entry.field.attr]' in source
    assert "Configuracao desconhecida ou ambigua." in source


def test_dashboard_settings_router_keeps_legacy_router_separate() -> None:
    source = Path("api/routes/admin/__init__.py").read_text(encoding="utf-8")

    assert "settings_router" in source
    assert "legacy_router" in source
    assert source.index("router.include_router(settings_router)") < source.index("router.include_router(legacy_router)")
