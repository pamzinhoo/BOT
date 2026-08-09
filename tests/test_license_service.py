from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from core.event_bus import EventBus
from core.events import (
    LICENSE_CREATED,
    LICENSE_GRANT_EVENTS,
    LICENSE_REVOKE_EVENTS,
    LICENSE_REVOKED,
)
from database.models.license import LicenseStatus
from database.models.license_event import LicenseEventType
from services.license_service import LicenseService
from tests._fakes_license import FakeDatabase, LicenseFakeStore, install_fake_repositories


@pytest.fixture
def store() -> LicenseFakeStore:
    return LicenseFakeStore()


@pytest.fixture
def license_service(monkeypatch, store: LicenseFakeStore) -> LicenseService:
    install_fake_repositories(monkeypatch, store)
    return LicenseService(FakeDatabase(store))


async def test_grant_creates_new_active_license(license_service: LicenseService, store: LicenseFakeStore) -> None:
    player_id, product_id = uuid.uuid4(), uuid.uuid4()

    license_row = await license_service.grant_or_renew(
        player_id, product_id, purchase_source="loja", external_reference="pay-1"
    )

    assert license_row.status == LicenseStatus.ACTIVE
    assert license_row.activated_at is not None
    assert len(store.licenses) == 1
    assert any(e.event_type == LicenseEventType.CREATED for e in store.events)


async def test_grant_is_idempotent_by_player_product(
    license_service: LicenseService, store: LicenseFakeStore
) -> None:
    player_id, product_id = uuid.uuid4(), uuid.uuid4()

    first = await license_service.grant_or_renew(player_id, product_id, purchase_source="loja")
    second = await license_service.grant_or_renew(player_id, product_id, purchase_source="loja")

    assert first.id == second.id
    assert len(store.licenses) == 1


async def test_grant_on_active_license_is_a_renewal(
    license_service: LicenseService, store: LicenseFakeStore
) -> None:
    player_id, product_id = uuid.uuid4(), uuid.uuid4()
    now = datetime.now(UTC)

    await license_service.grant_or_renew(player_id, product_id, purchase_source="assinatura", expires_at=now)
    renewed = await license_service.grant_or_renew(
        player_id, product_id, purchase_source="assinatura", expires_at=now + timedelta(days=30)
    )

    assert renewed.status == LicenseStatus.ACTIVE
    assert renewed.expires_at == now + timedelta(days=30)
    assert any(e.event_type == LicenseEventType.RENEWED for e in store.events)


async def test_revoke_marks_active_license_revoked(
    license_service: LicenseService, store: LicenseFakeStore
) -> None:
    player_id, product_id = uuid.uuid4(), uuid.uuid4()
    license_row = await license_service.grant_or_renew(player_id, product_id, purchase_source="loja")

    revoked = await license_service.revoke(license_row.id, reason="reembolso")

    assert revoked is not None
    assert revoked.status == LicenseStatus.REVOKED
    assert revoked.revoked_reason == "reembolso"
    assert any(e.event_type == LicenseEventType.REVOKED for e in store.events)


async def test_revoke_is_idempotent_noop_when_not_active(
    license_service: LicenseService, store: LicenseFakeStore
) -> None:
    player_id, product_id = uuid.uuid4(), uuid.uuid4()
    license_row = await license_service.grant_or_renew(player_id, product_id, purchase_source="loja")
    await license_service.revoke(license_row.id, reason="primeira revogacao")
    events_after_first = len(store.events)

    result = await license_service.revoke(license_row.id, reason="segunda tentativa")

    assert result.status == LicenseStatus.REVOKED
    assert result.revoked_reason == "primeira revogacao"  # nao sobrescreve
    assert len(store.events) == events_after_first  # nenhum evento novo


async def test_revoke_unknown_license_returns_none(license_service: LicenseService) -> None:
    assert await license_service.revoke(uuid.uuid4(), reason="x") is None


async def test_revoke_by_player_product_without_license_returns_none(
    license_service: LicenseService,
) -> None:
    result = await license_service.revoke_by_player_product(uuid.uuid4(), uuid.uuid4(), reason="assinatura vencida")
    assert result is None


async def test_revoke_by_player_product_revokes_matching_license(
    license_service: LicenseService, store: LicenseFakeStore
) -> None:
    player_id, product_id = uuid.uuid4(), uuid.uuid4()
    await license_service.grant_or_renew(player_id, product_id, purchase_source="assinatura")

    revoked = await license_service.revoke_by_player_product(player_id, product_id, reason="assinatura vencida")

    assert revoked is not None
    assert revoked.status == LicenseStatus.REVOKED


async def test_reactivation_after_revoke_grants_again(
    license_service: LicenseService, store: LicenseFakeStore
) -> None:
    player_id, product_id = uuid.uuid4(), uuid.uuid4()
    license_row = await license_service.grant_or_renew(player_id, product_id, purchase_source="assinatura")
    await license_service.revoke(license_row.id, reason="assinatura vencida")

    reactivated = await license_service.grant_or_renew(player_id, product_id, purchase_source="assinatura")

    assert reactivated.id == license_row.id
    assert reactivated.status == LicenseStatus.ACTIVE
    assert reactivated.revoked_at is None
    assert reactivated.revoked_reason is None
    assert any(e.event_type == LicenseEventType.REACTIVATED for e in store.events)


async def test_expire_license_marks_expired(license_service: LicenseService, store: LicenseFakeStore) -> None:
    player_id, product_id = uuid.uuid4(), uuid.uuid4()
    license_row = await license_service.grant_or_renew(player_id, product_id, purchase_source="assinatura")

    expired = await license_service.expire_license(license_row.id)

    assert expired is not None
    assert expired.status == LicenseStatus.EXPIRED
    assert any(e.event_type == LicenseEventType.EXPIRED for e in store.events)


async def test_has_active_license(license_service: LicenseService) -> None:
    player_id, product_id = uuid.uuid4(), uuid.uuid4()
    assert await license_service.has_active_license(player_id, product_id) is False

    await license_service.grant_or_renew(player_id, product_id, purchase_source="loja")

    assert await license_service.has_active_license(player_id, product_id) is True


# --- EventBus (Fase 5) -------------------------------------------------------
# Guarda de regressao: o `event_type` publicado no payload PRECISA ser um dos
# nomes de evento (core.events.LICENSE_*), nao o LicenseEventType.value cru —
# RoleSyncService decide conceder/remover cargo checando payload.event_type
# contra LICENSE_GRANT_EVENTS/LICENSE_REVOKE_EVENTS; um mismatch aqui faz o
# bot conceder cargo quando deveria remover (ou vice-versa) silenciosamente.


async def test_grant_publishes_event_with_grant_event_name(monkeypatch, store: LicenseFakeStore) -> None:
    install_fake_repositories(monkeypatch, store)
    received = []

    async def handler(payload):
        received.append(payload)

    bus = EventBus()
    bus.subscribe(LICENSE_CREATED, handler)
    service = LicenseService(FakeDatabase(store), bus)

    await service.grant_or_renew(uuid.uuid4(), uuid.uuid4(), purchase_source="loja")

    assert len(received) == 1
    assert received[0].event_type == LICENSE_CREATED
    assert received[0].event_type in LICENSE_GRANT_EVENTS


async def test_revoke_publishes_event_with_revoke_event_name(monkeypatch, store: LicenseFakeStore) -> None:
    install_fake_repositories(monkeypatch, store)
    received = []

    async def handler(payload):
        received.append(payload)

    bus = EventBus()
    bus.subscribe(LICENSE_REVOKED, handler)
    service = LicenseService(FakeDatabase(store), bus)
    license_row = await service.grant_or_renew(uuid.uuid4(), uuid.uuid4(), purchase_source="loja")

    await service.revoke(license_row.id, reason="teste")

    assert len(received) == 1
    assert received[0].event_type == LICENSE_REVOKED
    assert received[0].event_type in LICENSE_REVOKE_EVENTS


async def test_no_event_bus_is_safe_noop(store: LicenseFakeStore, monkeypatch) -> None:
    install_fake_repositories(monkeypatch, store)
    service = LicenseService(FakeDatabase(store))  # sem event_bus

    license_row = await service.grant_or_renew(uuid.uuid4(), uuid.uuid4(), purchase_source="loja")

    assert license_row is not None  # nao levanta sem event_bus configurado
