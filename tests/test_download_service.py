from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from database.models.download import DownloadStatus
from database.models.game_manifest import GameManifestEntry, ManifestEntryType
from database.models.launcher_version import LauncherPlatform, LauncherVersion
from database.models.player import Player
from services.download_service import DownloadError, DownloadService
from services.license_service import LicenseService
from tests._fakes_download import (
    DownloadFakeStore,
    FakeDatabase,
    FakeStorageProvider,
    install_fake_repositories,
)
from tests._fakes_license import FakeDatabase as LicenseFakeDatabase
from tests._fakes_license import LicenseFakeStore
from tests._fakes_license import install_fake_repositories as install_fake_license_repositories


class _FakeSettings:
    storage_download_ttl_seconds = 600


@pytest.fixture
def download_store() -> DownloadFakeStore:
    return DownloadFakeStore()


@pytest.fixture
def license_store() -> LicenseFakeStore:
    return LicenseFakeStore()


@pytest.fixture
def license_service(monkeypatch, license_store: LicenseFakeStore) -> LicenseService:
    install_fake_license_repositories(monkeypatch, license_store)
    return LicenseService(LicenseFakeDatabase(license_store))


@pytest.fixture
def download_service(
    monkeypatch, download_store: DownloadFakeStore, license_service: LicenseService
) -> tuple[DownloadService, FakeStorageProvider]:
    install_fake_repositories(monkeypatch, download_store)
    storage_provider = FakeStorageProvider()
    service = DownloadService(FakeDatabase(download_store), license_service, storage_provider, _FakeSettings())
    return service, storage_provider


def _player() -> Player:
    player = Player(discord_id=1, discord_username="tester", linked_at=datetime.now(UTC))
    player.id = uuid.uuid4()
    return player


def _seed_manifest_entry(
    store: DownloadFakeStore, product_id: uuid.UUID, *, sha256: str = "a" * 64
) -> GameManifestEntry:
    entry = GameManifestEntry(
        product_id=product_id,
        version="1.0.0",
        sha256=sha256,
        size_bytes=1024,
        storage_path=f"products/{product_id}/1.0.0.pkg",
        entry_type=ManifestEntryType.FULL,
        depends_on=[],
        is_current=True,
    )
    entry.id = uuid.uuid4()
    store.manifest_entries[entry.id] = entry
    return entry


async def test_authorize_download_requires_active_license(
    download_service: tuple[DownloadService, FakeStorageProvider],
) -> None:
    service, _ = download_service
    player = _player()

    with pytest.raises(DownloadError) as exc_info:
        await service.authorize_download(player, uuid.uuid4())
    assert exc_info.value.code == "license_required"


async def test_authorize_download_requires_manifest(
    download_service: tuple[DownloadService, FakeStorageProvider],
    license_service: LicenseService,
) -> None:
    service, _ = download_service
    player = _player()
    product_id = uuid.uuid4()
    await license_service.grant_or_renew(player.id, product_id, purchase_source="loja")

    with pytest.raises(DownloadError) as exc_info:
        await service.authorize_download(player, product_id)
    assert exc_info.value.code == "manifest_not_found"


async def test_authorize_download_returns_signed_url_and_creates_audit_row(
    download_service: tuple[DownloadService, FakeStorageProvider],
    download_store: DownloadFakeStore,
    license_service: LicenseService,
) -> None:
    service, storage = download_service
    player = _player()
    product_id = uuid.uuid4()
    await license_service.grant_or_renew(player.id, product_id, purchase_source="loja")
    entry = _seed_manifest_entry(download_store, product_id)

    authorization = await service.authorize_download(player, product_id)

    assert authorization.url.startswith("https://fake-storage.example/")
    assert authorization.sha256 == entry.sha256
    assert authorization.version == entry.version
    assert len(download_store.downloads) == 1
    download = next(iter(download_store.downloads.values()))
    assert download.status == DownloadStatus.AUTHORIZED
    assert download.player_id == player.id
    assert download.product_id == product_id
    assert storage.calls == [entry.storage_path]


async def test_authorize_download_wraps_storage_error(
    download_service: tuple[DownloadService, FakeStorageProvider],
    download_store: DownloadFakeStore,
    license_service: LicenseService,
) -> None:
    service, storage = download_service
    storage.fail = True
    player = _player()
    product_id = uuid.uuid4()
    await license_service.grant_or_renew(player.id, product_id, purchase_source="loja")
    _seed_manifest_entry(download_store, product_id)

    with pytest.raises(DownloadError) as exc_info:
        await service.authorize_download(player, product_id)
    assert exc_info.value.code == "storage_error"


async def test_authorize_download_without_storage_configured(
    download_store: DownloadFakeStore, license_service: LicenseService, monkeypatch
) -> None:
    install_fake_repositories(monkeypatch, download_store)
    service = DownloadService(FakeDatabase(download_store), license_service, None, _FakeSettings())
    player = _player()

    with pytest.raises(DownloadError) as exc_info:
        await service.authorize_download(player, uuid.uuid4())
    assert exc_info.value.code == "storage_not_configured"


async def test_complete_download_matching_checksum_marks_completed(
    download_service: tuple[DownloadService, FakeStorageProvider],
    download_store: DownloadFakeStore,
    license_service: LicenseService,
) -> None:
    service, _ = download_service
    player = _player()
    product_id = uuid.uuid4()
    await license_service.grant_or_renew(player.id, product_id, purchase_source="loja")
    entry = _seed_manifest_entry(download_store, product_id)
    authorization = await service.authorize_download(player, product_id)

    completed = await service.complete_download(
        authorization.download_id, player, client_sha256=entry.sha256, bytes_transferred=1024
    )

    assert completed.status == DownloadStatus.COMPLETED
    assert completed.failure_reason is None


async def test_complete_download_mismatched_checksum_marks_failed(
    download_service: tuple[DownloadService, FakeStorageProvider],
    download_store: DownloadFakeStore,
    license_service: LicenseService,
) -> None:
    service, _ = download_service
    player = _player()
    product_id = uuid.uuid4()
    await license_service.grant_or_renew(player.id, product_id, purchase_source="loja")
    _seed_manifest_entry(download_store, product_id)
    authorization = await service.authorize_download(player, product_id)

    completed = await service.complete_download(
        authorization.download_id, player, client_sha256="f" * 64, bytes_transferred=1024
    )

    assert completed.status == DownloadStatus.FAILED
    assert completed.failure_reason == "checksum_mismatch"


async def test_complete_download_is_idempotent(
    download_service: tuple[DownloadService, FakeStorageProvider],
    download_store: DownloadFakeStore,
    license_service: LicenseService,
) -> None:
    service, _ = download_service
    player = _player()
    product_id = uuid.uuid4()
    await license_service.grant_or_renew(player.id, product_id, purchase_source="loja")
    entry = _seed_manifest_entry(download_store, product_id)
    authorization = await service.authorize_download(player, product_id)

    first = await service.complete_download(authorization.download_id, player, client_sha256=entry.sha256)
    second = await service.complete_download(authorization.download_id, player, client_sha256="f" * 64)

    assert first.status == DownloadStatus.COMPLETED
    assert second.status == DownloadStatus.COMPLETED  # nao foi sobrescrito pelo segundo report


async def test_complete_download_rejects_other_players_download(
    download_service: tuple[DownloadService, FakeStorageProvider],
    download_store: DownloadFakeStore,
    license_service: LicenseService,
) -> None:
    service, _ = download_service
    owner = _player()
    intruder = _player()
    product_id = uuid.uuid4()
    await license_service.grant_or_renew(owner.id, product_id, purchase_source="loja")
    entry = _seed_manifest_entry(download_store, product_id)
    authorization = await service.authorize_download(owner, product_id)

    with pytest.raises(DownloadError) as exc_info:
        await service.complete_download(authorization.download_id, intruder, client_sha256=entry.sha256)
    assert exc_info.value.code == "download_not_found"


async def test_authorize_launcher_update_no_license_required(
    download_service: tuple[DownloadService, FakeStorageProvider], download_store: DownloadFakeStore
) -> None:
    service, storage = download_service
    version_row = LauncherVersion(
        version="1.2.0",
        platform=LauncherPlatform.WINDOWS,
        sha256="b" * 64,
        size_bytes=2048,
        storage_path="launcher/windows/1.2.0.pkg",
        is_mandatory=True,
        is_current=True,
    )
    version_row.id = uuid.uuid4()
    download_store.launcher_versions[LauncherPlatform.WINDOWS] = version_row

    authorization = await service.authorize_launcher_update(LauncherPlatform.WINDOWS)

    assert authorization.version == "1.2.0"
    assert authorization.is_mandatory is True
    assert storage.calls == [version_row.storage_path]


async def test_authorize_launcher_update_missing_version(
    download_service: tuple[DownloadService, FakeStorageProvider],
) -> None:
    service, _ = download_service
    with pytest.raises(DownloadError) as exc_info:
        await service.authorize_launcher_update(LauncherPlatform.LINUX)
    assert exc_info.value.code == "version_not_found"
