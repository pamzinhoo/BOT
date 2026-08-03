from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from database.models.partnership_settings import PartnershipMode
from services.partnership_service import (
    PartnershipCooldownError,
    PartnershipError,
    PartnershipService,
    _Space,
    contains_external_link,
    cooldown_remaining,
    member_has_role,
    member_is_partnership_staff,
    render_pre_message,
    slugify,
)

_NOW = datetime.now(UTC)


# --- slugify ------------------------------------------------------------------


def test_slugify_lowercases_and_hyphenates() -> None:
    assert slugify("Front Design") == "front-design"
    assert slugify("Servidor Limerence!!") == "servidor-limerence"


def test_slugify_falls_back_when_name_has_no_valid_chars() -> None:
    assert slugify("!!! ???") == "parceiro"


def test_slugify_truncates_long_names() -> None:
    assert len(slugify("a" * 200)) <= 90


# --- contains_external_link -----------------------------------------------------


def test_contains_external_link_detects_http_and_https() -> None:
    assert contains_external_link("veja http://exemplo.com") is True
    assert contains_external_link("veja https://exemplo.com") is True


def test_contains_external_link_false_for_plain_text() -> None:
    assert contains_external_link("nenhum link aqui, so texto normal") is False


# --- cooldown_remaining ----------------------------------------------------------


def test_cooldown_remaining_none_on_first_publish() -> None:
    assert cooldown_remaining(24, None, _NOW) is None


def test_cooldown_remaining_blocks_within_window() -> None:
    last = _NOW - timedelta(hours=2)
    remaining = cooldown_remaining(24, last, _NOW)
    assert remaining is not None
    assert timedelta(hours=21) < remaining <= timedelta(hours=22)


def test_cooldown_remaining_none_after_window_elapses() -> None:
    last = _NOW - timedelta(hours=25)
    assert cooldown_remaining(24, last, _NOW) is None


def test_partnership_cooldown_error_message_includes_wait_time() -> None:
    error = PartnershipCooldownError(timedelta(hours=2))
    assert "Aguarde" in str(error)


# --- render_pre_message ----------------------------------------------------------


def test_render_pre_message_includes_here_when_allowed() -> None:
    result = render_pre_message("📢 {here}\n\nNovidade!", allow_here=True)
    assert "@here" in result


def test_render_pre_message_omits_here_when_disallowed() -> None:
    result = render_pre_message("📢 {here}\n\nNovidade!", allow_here=False)
    assert "@here" not in result
    assert "Novidade!" in result


# --- roles / staff ----------------------------------------------------------------


def _fake_member(*, role_ids: list[int], is_admin: bool = False) -> discord.Member:
    member = MagicMock(spec=discord.Member)
    member.roles = [SimpleNamespace(id=rid) for rid in role_ids]
    member.guild_permissions = SimpleNamespace(administrator=is_admin)
    return member


def test_member_has_role_true_when_present() -> None:
    member = _fake_member(role_ids=[1, 2, 3])
    assert member_has_role(member, 2) is True


def test_member_has_role_false_when_absent_or_none_configured() -> None:
    member = _fake_member(role_ids=[1, 2, 3])
    assert member_has_role(member, 999) is False
    assert member_has_role(member, None) is False


def test_member_is_partnership_staff_via_configured_role() -> None:
    member = _fake_member(role_ids=[42])
    settings = SimpleNamespace(staff_role_id=42)
    assert member_is_partnership_staff(member, settings) is True


def test_member_is_partnership_staff_via_administrator() -> None:
    member = _fake_member(role_ids=[], is_admin=True)
    settings = SimpleNamespace(staff_role_id=999)
    assert member_is_partnership_staff(member, settings) is True


def test_member_is_partnership_staff_false_without_role_or_admin() -> None:
    member = _fake_member(role_ids=[1])
    settings = SimpleNamespace(staff_role_id=999)
    assert member_is_partnership_staff(member, settings) is False


# --- _resolve_existing_space (recuperacao apos exclusao manual) -------------------


def _make_service() -> PartnershipService:
    return PartnershipService.__new__(PartnershipService)


def _fake_record(**overrides: object) -> SimpleNamespace:
    base = dict(
        id="partnership-id", guild_id=1, owner_id=2, name="Front Design", description="desc",
        invite=None, banner=None, category_label=None, channel_id=None, thread_id=None,
        role_id=None, message_id=None, last_publish_at=None, created_at=_NOW,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_resolve_existing_space_returns_none_when_channel_was_manually_deleted() -> None:
    service = _make_service()
    guild = MagicMock(spec=discord.Guild)
    guild.get_channel.return_value = None
    record = _fake_record(channel_id=555)

    assert service._resolve_existing_space(guild, record) is None


def test_resolve_existing_space_reuses_existing_channel() -> None:
    service = _make_service()
    channel = MagicMock(spec=discord.TextChannel)
    guild = MagicMock(spec=discord.Guild)
    guild.get_channel.return_value = channel
    record = _fake_record(channel_id=555)

    space = service._resolve_existing_space(guild, record)
    assert space is not None
    assert space.kind == "channel"
    assert space.target is channel


def test_resolve_existing_space_returns_none_when_thread_was_manually_deleted() -> None:
    service = _make_service()
    guild = MagicMock(spec=discord.Guild)
    guild.get_thread.return_value = None
    record = _fake_record(thread_id=777)

    assert service._resolve_existing_space(guild, record) is None


# --- _delete_old_message (ignora exclusao manual) ---------------------------------


async def test_delete_old_message_ignores_already_deleted_message() -> None:
    service = _make_service()
    response = MagicMock()
    response.status = 404
    response.reason = "Not Found"
    channel = MagicMock()
    channel.fetch_message = AsyncMock(side_effect=discord.NotFound(response, "Unknown Message"))
    space = _Space(kind="channel", target=channel)

    await service._delete_old_message(space, 123)  # nao deve levantar excecao


async def test_delete_old_message_skips_for_brand_new_forum_thread() -> None:
    service = _make_service()
    channel = MagicMock()
    channel.fetch_message = AsyncMock()
    space = _Space(kind="forum_new", target=channel)

    await service._delete_old_message(space, 123)
    channel.fetch_message.assert_not_called()


# --- publish(): validacoes acontecem antes de tocar Discord/banco -----------------


def _fake_settings(**overrides: object) -> SimpleNamespace:
    base = dict(
        enabled=True, mode=PartnershipMode.CHANNEL.value, staff_role_id=20,
        cooldown_hours=24, allow_here=True, pre_message=None, log_channel_id=None,
        max_description_length=500, allow_banner=True, allow_image=True, allow_invite=True,
        allow_external_links=True, category_channel_id=None, forum_channel_id=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _mock_partner_role(service: PartnershipService, role_id: int | None) -> None:
    service._get_guild_partner_role_id = AsyncMock(return_value=role_id)


async def test_publish_rejects_when_system_disabled() -> None:
    service = _make_service()
    service.get_settings = AsyncMock(return_value=_fake_settings(enabled=False))
    _mock_partner_role(service, 10)
    member = _fake_member(role_ids=[10])

    with pytest.raises(PartnershipError, match="desativado"):
        await service.publish(
            guild=MagicMock(), member=member, name="X", description="d",
            invite=None, banner=None, category_label=None,
        )


async def test_publish_rejects_member_without_partner_role() -> None:
    service = _make_service()
    service.get_settings = AsyncMock(return_value=_fake_settings())
    _mock_partner_role(service, 10)
    member = _fake_member(role_ids=[999])  # nao tem o cargo 10 configurado

    with pytest.raises(PartnershipError, match="cargo"):
        await service.publish(
            guild=MagicMock(), member=member, name="X", description="d",
            invite=None, banner=None, category_label=None,
        )


async def test_publish_rejects_description_over_limit() -> None:
    service = _make_service()
    service.get_settings = AsyncMock(return_value=_fake_settings(max_description_length=10))
    _mock_partner_role(service, 10)
    member = _fake_member(role_ids=[10])

    with pytest.raises(PartnershipError, match="excede"):
        await service.publish(
            guild=MagicMock(), member=member, name="X", description="a" * 50,
            invite=None, banner=None, category_label=None,
        )


async def test_publish_rejects_external_link_when_disallowed() -> None:
    service = _make_service()
    service.get_settings = AsyncMock(return_value=_fake_settings(allow_external_links=False))
    _mock_partner_role(service, 10)
    member = _fake_member(role_ids=[10])

    with pytest.raises(PartnershipError, match="Links externos"):
        await service.publish(
            guild=MagicMock(), member=member, name="X", description="olha https://spam.com",
            invite=None, banner=None, category_label=None,
        )


async def test_publish_full_flow_calls_helpers_in_order_and_persists_message(monkeypatch) -> None:
    service = _make_service()
    settings = _fake_settings()
    service.get_settings = AsyncMock(return_value=settings)
    _mock_partner_role(service, 10)

    record = _fake_record(message_id=None)
    upsert = AsyncMock(return_value=(record, True))
    monkeypatch.setattr(service, "_upsert_record", upsert)

    space = _Space(kind="channel", target=MagicMock(), new_channel_id=999, new_role_id=888)
    monkeypatch.setattr(service, "_ensure_space", AsyncMock(return_value=space))

    persisted = _fake_record(channel_id=999, role_id=888, message_id=None)
    persist_ids = AsyncMock(return_value=persisted)
    monkeypatch.setattr(service, "_persist_ids", persist_ids)

    delete_old = AsyncMock()
    monkeypatch.setattr(service, "_delete_old_message", delete_old)

    message = MagicMock(id=12345)
    monkeypatch.setattr(service, "_send_publication", AsyncMock(return_value=(message, None)))
    monkeypatch.setattr(service, "_record_audit", AsyncMock())
    monkeypatch.setattr(service, "_send_log", AsyncMock())

    member = _fake_member(role_ids=[10])
    result = await service.publish(
        guild=MagicMock(), member=member, name="Front Design", description="uma comunidade legal",
        invite=None, banner=None, category_label="Design",
    )

    upsert.assert_awaited_once()
    delete_old.assert_not_awaited()  # record.message_id era None na 1a publicacao
    assert result is persisted  # resultado vem do ultimo _persist_ids mockado
    persist_ids.assert_awaited()


async def test_publish_deletes_old_message_when_republishing(monkeypatch) -> None:
    service = _make_service()
    settings = _fake_settings()
    service.get_settings = AsyncMock(return_value=settings)
    _mock_partner_role(service, 10)

    record = _fake_record(channel_id=999, message_id=555)
    monkeypatch.setattr(service, "_upsert_record", AsyncMock(return_value=(record, False)))

    space = _Space(kind="channel", target=MagicMock())
    monkeypatch.setattr(service, "_ensure_space", AsyncMock(return_value=space))
    monkeypatch.setattr(service, "_persist_ids", AsyncMock(return_value=record))
    delete_old = AsyncMock()
    monkeypatch.setattr(service, "_delete_old_message", delete_old)
    message = MagicMock(id=777)
    monkeypatch.setattr(service, "_send_publication", AsyncMock(return_value=(message, None)))
    monkeypatch.setattr(service, "_record_audit", AsyncMock())
    monkeypatch.setattr(service, "_send_log", AsyncMock())

    member = _fake_member(role_ids=[10])
    await service.publish(
        guild=MagicMock(), member=member, name="Front Design", description="atualizacao",
        invite=None, banner=None, category_label=None,
    )

    delete_old.assert_awaited_once_with(space, 555)


# --- remove(): somente staff --------------------------------------------------------


async def test_remove_rejects_non_staff_actor() -> None:
    service = _make_service()
    service.get_settings = AsyncMock(return_value=_fake_settings(staff_role_id=20))
    actor = _fake_member(role_ids=[1])  # nao tem o cargo de staff nem eh admin

    with pytest.raises(PartnershipError, match="staff"):
        await service.remove(guild=MagicMock(), actor=actor)
