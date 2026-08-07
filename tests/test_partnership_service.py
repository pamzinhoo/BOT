from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from database.models.partnership_settings import PartnershipRoleRemovedAction
from services.partnership_service import (
    PartnershipService,
    member_has_partnership_role,
    member_has_role,
    member_is_partnership_staff,
    render_announcement,
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


# --- render_announcement -------------------------------------------------------


def test_render_announcement_replaces_channel_placeholder() -> None:
    result = render_announcement("Confira {channel}", channel_id=999, mention_type="none")
    assert result == "Confira <#999>"


def test_render_announcement_here_mention() -> None:
    result = render_announcement("{mention} confira {channel}", channel_id=1, mention_type="here")
    assert "@here" in result


def test_render_announcement_everyone_mention() -> None:
    result = render_announcement("{mention} confira {channel}", channel_id=1, mention_type="everyone")
    assert "@everyone" in result


def test_render_announcement_no_mention_by_default() -> None:
    result = render_announcement("{mention}confira {channel}", channel_id=1, mention_type="none")
    assert "@" not in result.split("confira")[0]


# --- roles / staff ----------------------------------------------------------------


def _fake_member(*, role_ids: list[int], is_admin: bool = False, guild: discord.Guild | None = None) -> discord.Member:
    member = MagicMock(spec=discord.Member)
    member.roles = [SimpleNamespace(id=rid) for rid in role_ids]
    member.guild_permissions = SimpleNamespace(administrator=is_admin)
    member.guild = guild or MagicMock(spec=discord.Guild)
    member.display_name = "Pam"
    return member


def test_member_has_role_true_when_present() -> None:
    member = _fake_member(role_ids=[1, 2, 3])
    assert member_has_role(member, 2) is True


def test_member_has_role_false_when_absent_or_none_configured() -> None:
    member = _fake_member(role_ids=[1, 2, 3])
    assert member_has_role(member, 999) is False
    assert member_has_role(member, None) is False


def test_member_has_partnership_role_true_for_either_role() -> None:
    member = _fake_member(role_ids=[10])
    assert member_has_partnership_role(member, 10, 20) is True
    member2 = _fake_member(role_ids=[20])
    assert member_has_partnership_role(member2, 10, 20) is True


def test_member_has_partnership_role_false_for_neither() -> None:
    member = _fake_member(role_ids=[999])
    assert member_has_partnership_role(member, 10, 20) is False


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


# --- service helpers ----------------------------------------------------------------


def _make_service() -> PartnershipService:
    return PartnershipService.__new__(PartnershipService)


def _fake_settings(**overrides: object) -> SimpleNamespace:
    base = dict(
        enabled=True, auto_create=True, auto_move=True, staff_role_id=20,
        category_channel_id=None, archive_category_id=None,
        role_removed_action=PartnershipRoleRemovedAction.ARCHIVE.value,
        welcome_message=None, announcement_message=None, announcement_channel_id=None,
        announcement_interval_minutes=60, mention_type="none", last_announcement_at=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _fake_record(**overrides: object) -> SimpleNamespace:
    base = dict(
        id="partnership-id", guild_id=1, owner_id=2, channel_id=555, role_id=None,
        archived_at=None, last_announced_at=None, created_at=_NOW,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _fake_guild(*, channel: object | None = None, role: object | None = None) -> discord.Guild:
    guild = MagicMock(spec=discord.Guild)
    guild.id = 1
    guild.get_channel.return_value = channel
    guild.get_role.return_value = role
    return guild


# --- handle_role_gained --------------------------------------------------------------


async def test_handle_role_gained_noop_when_disabled() -> None:
    service = _make_service()
    service.get_settings = AsyncMock(return_value=_fake_settings(enabled=False))
    service._create_new = AsyncMock()
    member = _fake_member(role_ids=[])

    await service.handle_role_gained(member)

    service._create_new.assert_not_awaited()


async def test_handle_role_gained_noop_when_auto_create_disabled() -> None:
    service = _make_service()
    service.get_settings = AsyncMock(return_value=_fake_settings(auto_create=False))
    service._create_new = AsyncMock()
    member = _fake_member(role_ids=[])

    await service.handle_role_gained(member)

    service._create_new.assert_not_awaited()


async def test_handle_role_gained_creates_channel_when_no_record() -> None:
    service = _make_service()
    service.get_settings = AsyncMock(return_value=_fake_settings())
    service.get_partner_role_ids = AsyncMock(return_value=(10, None))
    service.get_partnership = AsyncMock(return_value=None)
    service._create_new = AsyncMock()
    member = _fake_member(role_ids=[10], guild=_fake_guild())

    await service.handle_role_gained(member)

    service._create_new.assert_awaited_once()


async def test_handle_role_gained_recreates_when_channel_was_deleted() -> None:
    service = _make_service()
    service.get_settings = AsyncMock(return_value=_fake_settings())
    service.get_partner_role_ids = AsyncMock(return_value=(10, None))
    record = _fake_record(channel_id=555)
    service.get_partnership = AsyncMock(return_value=record)
    service._delete_record = AsyncMock()
    service._create_new = AsyncMock()
    guild = _fake_guild(channel=None)  # canal ja nao existe mais
    member = _fake_member(role_ids=[10], guild=guild)

    await service.handle_role_gained(member)

    service._delete_record.assert_awaited_once_with(record.id)
    service._create_new.assert_awaited_once()


async def test_handle_role_gained_restores_archived_channel() -> None:
    service = _make_service()
    service.get_settings = AsyncMock(return_value=_fake_settings())
    service.get_partner_role_ids = AsyncMock(return_value=(10, None))
    record = _fake_record(archived_at=_NOW)
    service.get_partnership = AsyncMock(return_value=record)
    service._restore = AsyncMock()
    channel = MagicMock(spec=discord.TextChannel)
    guild = _fake_guild(channel=channel)
    member = _fake_member(role_ids=[10], guild=guild)

    await service.handle_role_gained(member)

    service._restore.assert_awaited_once()


async def test_handle_role_gained_only_syncs_permissions_when_already_active() -> None:
    service = _make_service()
    service.get_settings = AsyncMock(return_value=_fake_settings())
    service.get_partner_role_ids = AsyncMock(return_value=(10, None))
    record = _fake_record(archived_at=None)
    service.get_partnership = AsyncMock(return_value=record)
    service._create_new = AsyncMock()
    service._restore = AsyncMock()
    service._apply_overwrites = AsyncMock()
    channel = MagicMock(spec=discord.TextChannel)
    guild = _fake_guild(channel=channel)
    member = _fake_member(role_ids=[10], guild=guild)

    await service.handle_role_gained(member)

    service._create_new.assert_not_awaited()
    service._restore.assert_not_awaited()
    service._apply_overwrites.assert_awaited_once()


# --- handle_role_lost -----------------------------------------------------------------


async def test_handle_role_lost_noop_when_no_record() -> None:
    service = _make_service()
    service.get_settings = AsyncMock(return_value=_fake_settings())
    service.get_partnership = AsyncMock(return_value=None)
    service._archive = AsyncMock()
    service._delete_channel_and_role = AsyncMock()
    member = _fake_member(role_ids=[])

    await service.handle_role_lost(member)

    service._archive.assert_not_awaited()
    service._delete_channel_and_role.assert_not_awaited()


async def test_handle_role_lost_noop_when_action_is_none() -> None:
    service = _make_service()
    service.get_settings = AsyncMock(
        return_value=_fake_settings(role_removed_action=PartnershipRoleRemovedAction.NONE.value)
    )
    service.get_partnership = AsyncMock(return_value=_fake_record())
    service._archive = AsyncMock()
    service._delete_channel_and_role = AsyncMock()
    member = _fake_member(role_ids=[], guild=_fake_guild(channel=MagicMock()))

    await service.handle_role_lost(member)

    service._archive.assert_not_awaited()
    service._delete_channel_and_role.assert_not_awaited()


async def test_handle_role_lost_noop_when_already_archived() -> None:
    service = _make_service()
    service.get_settings = AsyncMock(return_value=_fake_settings())
    service.get_partnership = AsyncMock(return_value=_fake_record(archived_at=_NOW))
    service._archive = AsyncMock()
    member = _fake_member(role_ids=[])

    await service.handle_role_lost(member)

    service._archive.assert_not_awaited()


async def test_handle_role_lost_archives_by_default() -> None:
    service = _make_service()
    service.get_settings = AsyncMock(return_value=_fake_settings())
    service.get_partnership = AsyncMock(return_value=_fake_record())
    service._archive = AsyncMock()
    service._delete_channel_and_role = AsyncMock()
    channel = MagicMock(spec=discord.TextChannel)
    member = _fake_member(role_ids=[], guild=_fake_guild(channel=channel))

    await service.handle_role_lost(member)

    service._archive.assert_awaited_once()
    service._delete_channel_and_role.assert_not_awaited()


async def test_handle_role_lost_deletes_when_configured() -> None:
    service = _make_service()
    service.get_settings = AsyncMock(
        return_value=_fake_settings(role_removed_action=PartnershipRoleRemovedAction.DELETE.value)
    )
    service.get_partnership = AsyncMock(return_value=_fake_record())
    service._archive = AsyncMock()
    service._delete_channel_and_role = AsyncMock()
    channel = MagicMock(spec=discord.TextChannel)
    member = _fake_member(role_ids=[], guild=_fake_guild(channel=channel))

    await service.handle_role_lost(member)

    service._delete_channel_and_role.assert_awaited_once()
    service._archive.assert_not_awaited()


# --- reconcile_guild ------------------------------------------------------------------


async def test_reconcile_guild_creates_for_holders_without_record() -> None:
    service = _make_service()
    service.get_settings = AsyncMock(return_value=_fake_settings())
    service.get_partner_role_ids = AsyncMock(return_value=(10, None))
    service.handle_role_gained = AsyncMock()
    service.handle_role_lost = AsyncMock()

    member = _fake_member(role_ids=[10])
    member.id = 2
    role = SimpleNamespace(id=10, members=[member])
    guild = MagicMock(spec=discord.Guild)
    guild.id = 1
    guild.get_role.return_value = role
    guild.get_member.return_value = member

    from database.repositories.partnership_repository import PartnershipRepository

    fake_session = MagicMock()
    fake_session.flush = AsyncMock()
    fake_repo = MagicMock(spec=PartnershipRepository)
    fake_repo.list_active_by_guild = AsyncMock(return_value=[])
    service._database = SimpleNamespace(session=lambda: _FakeSessionCtx(fake_session))

    import services.partnership_service as module

    original_repo_cls = module.PartnershipRepository
    module.PartnershipRepository = lambda session: fake_repo
    try:
        await service.reconcile_guild(guild)
    finally:
        module.PartnershipRepository = original_repo_cls

    service.handle_role_gained.assert_awaited_once_with(member)
    service.handle_role_lost.assert_not_awaited()


async def test_reconcile_guild_removes_for_records_without_holder() -> None:
    service = _make_service()
    service.get_settings = AsyncMock(return_value=_fake_settings())
    service.get_partner_role_ids = AsyncMock(return_value=(10, None))
    service.handle_role_gained = AsyncMock()
    service.handle_role_lost = AsyncMock()

    member = _fake_member(role_ids=[])
    member.id = 2
    guild = MagicMock(spec=discord.Guild)
    guild.id = 1
    guild.get_role.return_value = None
    guild.get_member.return_value = member

    from database.repositories.partnership_repository import PartnershipRepository

    fake_session = MagicMock()
    fake_session.flush = AsyncMock()
    fake_repo = MagicMock(spec=PartnershipRepository)
    fake_repo.list_active_by_guild = AsyncMock(return_value=[_fake_record(owner_id=2)])
    service._database = SimpleNamespace(session=lambda: _FakeSessionCtx(fake_session))

    import services.partnership_service as module

    original_repo_cls = module.PartnershipRepository
    module.PartnershipRepository = lambda session: fake_repo
    try:
        await service.reconcile_guild(guild)
    finally:
        module.PartnershipRepository = original_repo_cls

    service.handle_role_lost.assert_awaited_once_with(member)
    service.handle_role_gained.assert_not_awaited()


# --- run_announcement_tick -------------------------------------------------------------


class _FakeSessionCtx:
    def __init__(self, session: object) -> None:
        self._session = session

    async def __aenter__(self) -> object:
        return self._session

    async def __aexit__(self, *args: object) -> bool:
        return False


async def test_announcement_tick_skips_when_disabled() -> None:
    service = _make_service()
    service.get_settings = AsyncMock(return_value=_fake_settings(enabled=False))
    guild = MagicMock(spec=discord.Guild)

    await service.run_announcement_tick(guild)  # nao deve levantar excecao nem acessar banco


async def test_announcement_tick_skips_when_interval_not_elapsed() -> None:
    service = _make_service()
    settings = _fake_settings(
        announcement_channel_id=999, last_announcement_at=_NOW - timedelta(minutes=5),
        announcement_interval_minutes=60,
    )
    service.get_settings = AsyncMock(return_value=settings)
    guild = MagicMock(spec=discord.Guild)
    guild.get_channel = MagicMock()

    await service.run_announcement_tick(guild)

    guild.get_channel.assert_not_called()


async def test_announcement_tick_sends_and_updates_rotation() -> None:
    service = _make_service()
    settings = _fake_settings(announcement_channel_id=999, announcement_message="Confira {channel}")
    service.get_settings = AsyncMock(return_value=settings)
    service.update_settings = AsyncMock()
    service._record_audit = AsyncMock()

    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    guild = MagicMock(spec=discord.Guild)
    guild.id = 1
    guild.get_channel.return_value = channel

    partner = _fake_record(channel_id=555, owner_id=2)
    fake_repo = MagicMock()
    fake_repo.get_next_to_announce = AsyncMock(return_value=partner)
    fake_session = MagicMock()
    fake_session.flush = AsyncMock()
    service._database = SimpleNamespace(session=lambda: _FakeSessionCtx(fake_session))

    import services.partnership_service as module

    original_repo_cls = module.PartnershipRepository
    module.PartnershipRepository = lambda session: fake_repo
    try:
        await service.run_announcement_tick(guild)
    finally:
        module.PartnershipRepository = original_repo_cls

    channel.send.assert_awaited_once()
    assert "<#555>" in channel.send.call_args.args[0]
    service._record_audit.assert_awaited_once()
    service.update_settings.assert_awaited_once()


async def test_announcement_tick_no_partner_still_updates_timestamp() -> None:
    service = _make_service()
    settings = _fake_settings(announcement_channel_id=999)
    service.get_settings = AsyncMock(return_value=settings)
    service.update_settings = AsyncMock()

    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    guild = MagicMock(spec=discord.Guild)
    guild.id = 1
    guild.get_channel.return_value = channel

    fake_repo = MagicMock()
    fake_repo.get_next_to_announce = AsyncMock(return_value=None)
    fake_session = MagicMock()
    fake_session.flush = AsyncMock()
    service._database = SimpleNamespace(session=lambda: _FakeSessionCtx(fake_session))

    import services.partnership_service as module

    original_repo_cls = module.PartnershipRepository
    module.PartnershipRepository = lambda session: fake_repo
    try:
        await service.run_announcement_tick(guild)
    finally:
        module.PartnershipRepository = original_repo_cls

    channel.send.assert_not_awaited()
    service.update_settings.assert_awaited_once()


# --- overwrites --------------------------------------------------------------------


def test_build_overwrites_active_channel_allows_partner_to_write() -> None:
    service = _make_service()
    guild = MagicMock(spec=discord.Guild)
    guild.default_role = MagicMock(spec=discord.Role, id=0)
    partner_role = MagicMock(spec=discord.Role, id=10)
    guild.get_role = MagicMock(side_effect=lambda rid: {10: partner_role}.get(rid))
    settings = _fake_settings(staff_role_id=None)

    overwrites = service._build_overwrites(guild, settings, 10, None, None, None, readonly=False)

    assert overwrites[partner_role].send_messages is True
    assert overwrites[guild.default_role].send_messages is False


def test_build_overwrites_readonly_blocks_everyone_from_writing() -> None:
    service = _make_service()
    guild = MagicMock(spec=discord.Guild)
    guild.default_role = MagicMock(spec=discord.Role, id=0)
    partner_role = MagicMock(spec=discord.Role, id=10)
    guild.get_role = MagicMock(side_effect=lambda rid: {10: partner_role}.get(rid))
    settings = _fake_settings(staff_role_id=None)

    overwrites = service._build_overwrites(guild, settings, 10, None, None, None, readonly=True)

    assert overwrites[partner_role].send_messages is False
    assert overwrites[partner_role].view_channel is True


def test_build_overwrites_inherits_category_permissions() -> None:
    service = _make_service()
    guild = MagicMock(spec=discord.Guild)
    guild.default_role = MagicMock(spec=discord.Role, id=0)
    other_role = MagicMock(spec=discord.Role, id=99)
    guild.get_role = MagicMock(side_effect=lambda rid: None)
    settings = _fake_settings(staff_role_id=None)

    category_overwrite = discord.PermissionOverwrite(manage_messages=True)
    category = MagicMock(spec=discord.CategoryChannel)
    category.overwrites = {other_role: category_overwrite}

    overwrites = service._build_overwrites(guild, settings, None, None, None, category, readonly=False)

    assert overwrites[other_role] is category_overwrite
    assert overwrites[other_role].manage_messages is True
    assert overwrites[guild.default_role].view_channel is True
