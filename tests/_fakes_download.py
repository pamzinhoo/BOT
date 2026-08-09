"""Duplas de teste (fakes) pro DownloadService — mesmo padrao de
tests/_fakes_license.py."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from database.models.download import Download
from database.models.game_manifest import GameManifestEntry, ManifestEntryType
from database.models.launcher_version import LauncherPlatform, LauncherVersion
from providers.storage.base import StorageError, StorageProvider


@dataclass
class DownloadFakeStore:
    downloads: dict[uuid.UUID, Download] = field(default_factory=dict)
    manifest_entries: dict[uuid.UUID, GameManifestEntry] = field(default_factory=dict)
    launcher_versions: dict[LauncherPlatform, LauncherVersion] = field(default_factory=dict)


class FakeSession:
    async def flush(self) -> None:
        pass

    async def refresh(self, entity: object) -> None:
        pass


class FakeDatabase:
    def __init__(self, store: DownloadFakeStore) -> None:
        self.store = store

    @asynccontextmanager
    async def session(self):
        yield FakeSession()


def _new_id(entity: object) -> None:
    if getattr(entity, "id", None) is None:
        entity.id = uuid.uuid4()


class FakeDownloadRepository:
    def __init__(self, session: FakeSession, *, store: DownloadFakeStore) -> None:
        self._store = store

    async def add(self, entity: Download) -> Download:
        _new_id(entity)
        self._store.downloads[entity.id] = entity
        return entity

    async def get_by_id(self, id_: uuid.UUID) -> Download | None:
        return self._store.downloads.get(id_)

    async def get_by_id_locked(self, id_: uuid.UUID) -> Download | None:
        return self._store.downloads.get(id_)


class FakeGameManifestRepository:
    def __init__(self, session: FakeSession, *, store: DownloadFakeStore) -> None:
        self._store = store

    async def get_current(
        self, product_id: uuid.UUID, *, entry_type: ManifestEntryType = ManifestEntryType.FULL
    ) -> GameManifestEntry | None:
        return next(
            (
                entry
                for entry in self._store.manifest_entries.values()
                if entry.product_id == product_id and entry.entry_type == entry_type and entry.is_current
            ),
            None,
        )

    async def get_by_id(self, id_: uuid.UUID) -> GameManifestEntry | None:
        return self._store.manifest_entries.get(id_)


class FakeLauncherVersionRepository:
    def __init__(self, session: FakeSession, *, store: DownloadFakeStore) -> None:
        self._store = store

    async def get_current(self, platform: LauncherPlatform) -> LauncherVersion | None:
        return self._store.launcher_versions.get(platform)


class FakeStorageProvider(StorageProvider):
    name = "fake"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[str] = []

    def generate_download_url(
        self, storage_path: str, *, expires_in_seconds: int, filename: str | None = None
    ) -> str:
        self.calls.append(storage_path)
        if self.fail:
            raise StorageError("falha simulada de storage")
        return f"https://fake-storage.example/{storage_path}?ttl={expires_in_seconds}"


def install_fake_repositories(monkeypatch, store: DownloadFakeStore) -> None:
    monkeypatch.setattr(
        "services.download_service.DownloadRepository",
        lambda session: FakeDownloadRepository(session, store=store),
    )
    monkeypatch.setattr(
        "services.download_service.GameManifestRepository",
        lambda session: FakeGameManifestRepository(session, store=store),
    )
    monkeypatch.setattr(
        "services.download_service.LauncherVersionRepository",
        lambda session: FakeLauncherVersionRepository(session, store=store),
    )
