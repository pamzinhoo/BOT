from __future__ import annotations

from pathlib import Path


def test_app_shell_polls_readiness_only_until_ready() -> None:
    source = Path("frontend/src/components/AppShell.tsx").read_text(encoding="utf-8")
    assert 'api<Readiness>("/ready")' in source
    assert "query.state.data?.ready ? false : 2_000" in source
    assert "readyQuery.data?.ready ? false : 2_000" in source


def test_pages_distinguish_discord_startup_from_empty_guilds() -> None:
    for path in [
        "frontend/src/pages/OverviewPage.tsx",
        "frontend/src/pages/TicketsPage.tsx",
        "frontend/src/pages/SettingsPage.tsx",
        "frontend/src/pages/AuditPage.tsx",
        "frontend/src/pages/StaffPage.tsx",
        "frontend/src/pages/PanelsPage.tsx",
    ]:
        source = Path(path).read_text(encoding="utf-8")
        assert "Conectando ao Discord..." in source
        assert "Discord conectado, carregando servidores..." in source
        assert "Nenhum servidor disponível para este bot." in source
