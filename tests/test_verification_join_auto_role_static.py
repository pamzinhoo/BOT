from __future__ import annotations

from pathlib import Path


def test_member_join_grants_verified_role_when_verification_is_disabled() -> None:
    source = Path("cogs/verification.py").read_text(encoding="utf-8")

    assert "async def on_member_join" in source
    assert "prompt = await self.bot.verification_service.start_verification(member)" in source
    assert "if prompt is None:" in source
    assert "await self._grant_verified_role_when_disabled(member)" in source
    assert "async def _grant_verified_role_when_disabled" in source
    assert "settings.enabled" in source
    assert "settings.verified_role_id" in source
    assert "await member.add_roles" in source
    assert "Verificação desativada: cargo automático de entrada" in source
    assert "send_verification_prompt" in source
