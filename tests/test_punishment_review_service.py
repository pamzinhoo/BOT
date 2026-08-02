from __future__ import annotations

import uuid

import pytest

from database.models.punishment import PunishmentStatus, PunishmentType
from services.punishment_review_service import (
    PunishmentReviewError,
    PunishmentReviewService,
)


class _FakePunishment:
    def __init__(self, *, staff_id: int, status: PunishmentStatus, punishment_id=None):
        self.id = punishment_id or uuid.uuid4()
        self.staff_id = staff_id
        self.status = status
        self.user_id = 111
        self.user_name = "Alvo"
        self.punishment_code = "BAN-11111"


class _FakeAppeal:
    def __init__(self):
        self.id = uuid.uuid4()


class _FakeDecisionResult:
    def __init__(self, punishment, appeal):
        self.punishment = punishment
        self.appeal = appeal


class _FakeMember:
    def __init__(self, member_id: int, name: str = "Staff"):
        self.id = member_id
        self._name = name

    def __str__(self) -> str:
        return self._name


class _FakeGuild:
    def __init__(self, guild_id: int = 999):
        self.id = guild_id


class _FakePunishmentService:
    """Duck-typed stand-in pro PunishmentService — so os metodos usados pela
    PunishmentReviewService, sem tocar banco/Discord de verdade."""

    def __init__(self, punishment: _FakePunishment, appeal: _FakeAppeal | None = None):
        self.punishment = punishment
        self.appeal = appeal
        self.calls: list[tuple[str, dict]] = []

    async def get_by_id(self, punishment_id):
        return self.punishment

    async def get_pending_appeal(self, punishment_id):
        return self.appeal

    async def accept_appeal(self, **kwargs):
        self.calls.append(("accept_appeal", kwargs))
        self.punishment.status = PunishmentStatus.REVOKED
        return _FakeDecisionResult(self.punishment, self.appeal)

    async def deny_appeal(self, **kwargs):
        self.calls.append(("deny_appeal", kwargs))
        self.punishment.status = PunishmentStatus.ACTIVE
        return _FakeDecisionResult(self.punishment, self.appeal)

    async def resolve_review(self, **kwargs):
        self.calls.append(("resolve_review", kwargs))
        self.punishment.status = (
            PunishmentStatus.REVOKED if kwargs["approved"] else PunishmentStatus.ACTIVE
        )
        return self.punishment


class _FakeAuditLogService:
    def __init__(self):
        self.records: list[dict] = []

    async def record(self, **kwargs):
        self.records.append(kwargs)


def _make_service(punishment_service: _FakePunishmentService, audit: _FakeAuditLogService):
    return PunishmentReviewService(database=None, punishment_service=punishment_service, audit_log_service=audit)


def test_filter_types_mapping():
    assert PunishmentReviewService.filter_types("todos") is None
    assert PunishmentReviewService.filter_types("ban") == {PunishmentType.BAN, PunishmentType.BAN_TEMPORARIO}
    assert PunishmentReviewService.filter_types("timeout") == {PunishmentType.TIMEOUT}
    assert PunishmentReviewService.filter_types("kick") == {PunishmentType.KICK}
    assert PunishmentReviewService.filter_types("advertencia") == {PunishmentType.ADVERTENCIA}
    assert PunishmentReviewService.filter_types("lixo_desconhecido") is None


def test_paginate_first_page_and_total_pages():
    items = list(range(25))
    page_items, total_pages = PunishmentReviewService.paginate(items, 1)
    assert page_items == list(range(10))
    assert total_pages == 3


def test_paginate_next_page():
    items = list(range(25))
    page_items, total_pages = PunishmentReviewService.paginate(items, 2)
    assert page_items == list(range(10, 20))
    assert total_pages == 3


def test_paginate_refresh_same_page_is_stable():
    items = list(range(15))
    first_call, _ = PunishmentReviewService.paginate(items, 2)
    second_call, _ = PunishmentReviewService.paginate(items, 2)
    assert first_call == second_call == list(range(10, 15))


def test_paginate_clamps_page_out_of_range():
    items = list(range(5))
    page_items, total_pages = PunishmentReviewService.paginate(items, 99)
    assert total_pages == 1
    assert page_items == list(range(5))


def test_paginate_empty_list():
    page_items, total_pages = PunishmentReviewService.paginate([], 1)
    assert page_items == []
    assert total_pages == 1


def test_is_self_review_true_when_same_staff():
    punishment = _FakePunishment(staff_id=42, status=PunishmentStatus.PENDING_REVIEW)
    assert PunishmentReviewService.is_self_review(punishment, 42) is True


def test_is_self_review_false_when_different_staff():
    punishment = _FakePunishment(staff_id=42, status=PunishmentStatus.PENDING_REVIEW)
    assert PunishmentReviewService.is_self_review(punishment, 7) is False


async def test_accept_uses_accept_appeal_when_pending_appeal_exists():
    punishment = _FakePunishment(staff_id=1, status=PunishmentStatus.PENDING_REVIEW)
    appeal = _FakeAppeal()
    fake_service = _FakePunishmentService(punishment, appeal)
    audit = _FakeAuditLogService()
    service = _make_service(fake_service, audit)

    result = await service.accept(
        guild=_FakeGuild(), punishment_id=punishment.id, reviewer=_FakeMember(2), review_role_id=None
    )

    assert fake_service.calls[0][0] == "accept_appeal"
    assert result.punishment.status == PunishmentStatus.REVOKED
    assert audit.records[0]["action"] == "ACCEPT_APPEAL_FROM_PANEL"


async def test_accept_uses_resolve_review_when_no_appeal():
    punishment = _FakePunishment(staff_id=1, status=PunishmentStatus.PENDING_REVIEW)
    fake_service = _FakePunishmentService(punishment, appeal=None)
    audit = _FakeAuditLogService()
    service = _make_service(fake_service, audit)

    result = await service.accept(
        guild=_FakeGuild(), punishment_id=punishment.id, reviewer=_FakeMember(2), review_role_id=None
    )

    assert fake_service.calls[0][0] == "resolve_review"
    assert fake_service.calls[0][1]["approved"] is True
    assert result.punishment.status == PunishmentStatus.REVOKED


async def test_deny_uses_deny_appeal_when_pending_appeal_exists():
    punishment = _FakePunishment(staff_id=1, status=PunishmentStatus.PENDING_REVIEW)
    appeal = _FakeAppeal()
    fake_service = _FakePunishmentService(punishment, appeal)
    audit = _FakeAuditLogService()
    service = _make_service(fake_service, audit)

    result = await service.deny(
        guild=_FakeGuild(), punishment_id=punishment.id, reviewer=_FakeMember(2), reason="motivo", review_role_id=None
    )

    assert fake_service.calls[0][0] == "deny_appeal"
    assert result.punishment.status == PunishmentStatus.ACTIVE
    assert audit.records[0]["action"] == "DENY_APPEAL_FROM_PANEL"
    assert audit.records[0]["reason"] == "motivo"


async def test_deny_uses_resolve_review_when_no_appeal():
    punishment = _FakePunishment(staff_id=1, status=PunishmentStatus.PENDING_REVIEW)
    fake_service = _FakePunishmentService(punishment, appeal=None)
    audit = _FakeAuditLogService()
    service = _make_service(fake_service, audit)

    result = await service.deny(
        guild=_FakeGuild(), punishment_id=punishment.id, reviewer=_FakeMember(2), reason="motivo", review_role_id=None
    )

    assert fake_service.calls[0][0] == "resolve_review"
    assert fake_service.calls[0][1]["approved"] is False
    assert result.punishment.status == PunishmentStatus.ACTIVE


async def test_accept_blocks_self_review():
    punishment = _FakePunishment(staff_id=42, status=PunishmentStatus.PENDING_REVIEW)
    fake_service = _FakePunishmentService(punishment, appeal=None)
    audit = _FakeAuditLogService()
    service = _make_service(fake_service, audit)

    with pytest.raises(PunishmentReviewError):
        await service.accept(
            guild=_FakeGuild(), punishment_id=punishment.id, reviewer=_FakeMember(42), review_role_id=None
        )
    assert fake_service.calls == []


async def test_deny_blocks_self_review():
    punishment = _FakePunishment(staff_id=42, status=PunishmentStatus.PENDING_REVIEW)
    fake_service = _FakePunishmentService(punishment, appeal=None)
    audit = _FakeAuditLogService()
    service = _make_service(fake_service, audit)

    with pytest.raises(PunishmentReviewError):
        await service.deny(
            guild=_FakeGuild(),
            punishment_id=punishment.id,
            reviewer=_FakeMember(42),
            reason="motivo",
            review_role_id=None,
        )
    assert fake_service.calls == []


async def test_accept_blocks_when_punishment_no_longer_pending_review():
    punishment = _FakePunishment(staff_id=1, status=PunishmentStatus.ACTIVE)
    fake_service = _FakePunishmentService(punishment, appeal=None)
    audit = _FakeAuditLogService()
    service = _make_service(fake_service, audit)

    with pytest.raises(PunishmentReviewError):
        await service.accept(
            guild=_FakeGuild(), punishment_id=punishment.id, reviewer=_FakeMember(2), review_role_id=None
        )
    assert fake_service.calls == []


async def test_accept_blocks_when_punishment_not_found():
    fake_service = _FakePunishmentService(punishment=None, appeal=None)  # type: ignore[arg-type]
    fake_service.punishment = None
    audit = _FakeAuditLogService()
    service = _make_service(fake_service, audit)

    with pytest.raises(PunishmentReviewError):
        await service.accept(
            guild=_FakeGuild(), punishment_id=uuid.uuid4(), reviewer=_FakeMember(2), review_role_id=None
        )


def test_divergent_user_ids_flags_role_without_db_record():
    role_ids = {1, 2, 3}
    covered_ids = {2}
    assert PunishmentReviewService.divergent_user_ids(role_ids, covered_ids) == {1, 3}


def test_divergent_user_ids_empty_when_fully_covered():
    role_ids = {1, 2}
    covered_ids = {1, 2, 3}
    assert PunishmentReviewService.divergent_user_ids(role_ids, covered_ids) == set()


def test_denial_message_matches_spec():
    from views.pending_punishments_view import _DENIAL_MESSAGE

    assert _DENIAL_MESSAGE == "❌ Você não possui permissão para visualizar punições em análise."
