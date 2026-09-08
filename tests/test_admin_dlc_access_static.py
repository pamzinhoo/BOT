from __future__ import annotations

from pathlib import Path


def test_dashboard_dlc_access_listing_is_read_only() -> None:
    source = Path("api/routes/admin/dlcs_router.py").read_text(encoding="utf-8")
    page = Path("frontend/src/pages/DlcsPage.tsx").read_text(encoding="utf-8")
    api = Path("frontend/src/lib/api.ts").read_text(encoding="utf-8")

    assert '"/guild/{guild_id}/dlcs/{product_id}/access"' in source
    assert "License" in source
    assert "Player" in source
    assert "LicenseStatus" in source
    assert "role.members" in source
    assert "Somente leitura" in source
    access_block = source.split("async def dlc_access", 1)[1].split("@router.post", 1)[0]
    assert "external_reference" not in access_block
    assert "update_" not in access_block
    assert "message.delete" not in access_block
    assert "DlcAccessPayload" in api
    assert "DlcAccessItem" in api
    assert "Ver usuários" in page
    assert "Usuários com acesso à DLC" in page
    assert "ID Discord" in page
