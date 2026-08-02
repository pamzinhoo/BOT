from __future__ import annotations

from database.models.audit_log import AuditLogCategory
from database.models.punishment import PunishmentStatus
from utils.constants import (
    AUDIT_CATEGORY_COLORS,
    AUDIT_CATEGORY_LABELS,
    AUDIT_CATEGORY_TARGET_KIND,
    PUNISHMENT_STATUS_LABELS,
)


def test_every_audit_category_has_a_label() -> None:
    missing = [c for c in AuditLogCategory if c not in AUDIT_CATEGORY_LABELS]
    assert missing == []


def test_every_audit_category_has_a_color() -> None:
    missing = [c for c in AuditLogCategory if c not in AUDIT_CATEGORY_COLORS]
    assert missing == []


def test_every_audit_category_has_a_target_kind() -> None:
    missing = [c for c in AuditLogCategory if c not in AUDIT_CATEGORY_TARGET_KIND]
    assert missing == []


def test_every_punishment_status_has_a_label() -> None:
    missing = [s for s in PunishmentStatus if s not in PUNISHMENT_STATUS_LABELS]
    assert missing == []


def test_pending_review_counts_as_open_punishment() -> None:
    from database.models.punishment import UNRESOLVED_STATUSES

    statuses = {PunishmentStatus.ACTIVE, PunishmentStatus.PENDING_REVIEW, *UNRESOLVED_STATUSES}
    assert PunishmentStatus.PENDING_REVIEW in statuses


def test_moderacao_config_panel_exposes_review_fields() -> None:
    from views.master_config_view import _moderacao_category

    class _DummyConfigService:
        update = None

    class _DummyBot:
        config_service = _DummyConfigService()

    fields, _get_settings, _update_settings = _moderacao_category(_DummyBot())
    attrs = {field.attr for field in fields}
    assert {"review_role_id", "review_channel_id", "review_timeout_minutes"} <= attrs
