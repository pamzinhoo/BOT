from __future__ import annotations

from unittest.mock import MagicMock

import discord

from services.booster_service import render_placeholders


def _fake_member(*, guild_name: str = "Servidor Teste", member_count: int = 42) -> discord.Member:
    guild = MagicMock(spec=discord.Guild)
    guild.name = guild_name
    guild.member_count = member_count

    member = MagicMock(spec=discord.Member)
    member.mention = "<@123>"
    member.guild = guild
    return member


def _fake_role(name: str = "Booster") -> discord.Role:
    role = MagicMock(spec=discord.Role)
    role.mention = "<@&456>"
    role.name = name
    return role


def test_renders_all_placeholders() -> None:
    member = _fake_member()
    role = _fake_role()

    result = render_placeholders(
        "{user} impulsionou {server_name}, ganhou {role_name}, boost #{boost_count}, "
        "somos {member_count} membros.",
        member=member,
        role=role,
        boost_count=3,
    )

    assert result == (
        "<@123> impulsionou Servidor Teste, ganhou <@&456>, boost #3, somos 42 membros."
    )


def test_role_placeholder_falls_back_when_role_not_configured() -> None:
    member = _fake_member()

    result = render_placeholders("Cargo: {role_name}", member=member, role=None, boost_count=1)

    assert result == "Cargo: —"
