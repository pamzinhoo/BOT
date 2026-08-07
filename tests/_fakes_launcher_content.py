"""Duplas de teste (fakes) pro LauncherContentService."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from database.models.game_manifest import GameManifestEntry, ManifestEntryType
from database.models.launcher_news import LauncherNews
from database.models.launcher_version import LauncherPlatform, LauncherVersion


@dataclass
class LauncherContentFakeStore:
    news: list[LauncherNews] = field(default_factory=list)
    versions: dict[LauncherPlatform, LauncherVersion] = field(default_factory=dict)
    manifest_entries: dict[uuid.UUID, GameManifestEntry] = field(default_factory=dict)


class FakeSession:
    async def flush(self) -> None:
        pass


class FakeDatabase:
    def __init__(self, store: LauncherContentFakeStore) -> None:
        self.store = store

    @asynccontextmanager
    async def session(self):
        yield FakeSession()


class FakeLauncherNewsRepository:
    def __init__(self, session: FakeSession, *, store: LauncherContentFakeStore) -> None:
        self._store = store

    async def list_published(self, *, limit: int = 20) -> list[LauncherNews]:
        published = [n for n in self._store.news if n.is_published and n.deleted_at is None]
        return sorted(published, key=lambda n: n.published_at, reverse=True)[:limit]


class FakeLauncherVersionRepository:
    def __init__(self, session: FakeSession, *, store: LauncherContentFakeStore) -> None:
        self._store = store

    async def get_current(self, platform: LauncherPlatform) -> LauncherVersion | None:
        return self._store.versions.get(platform)


class FakeGameManifestRepository:
    def __init__(self, session: FakeSession, *, store: LauncherContentFakeStore) -> None:
        self._store = store

    async def get_current(
        self, product_id: uuid.UUID, *, entry_type: ManifestEntryType = ManifestEntryType.FULL
    ) -> GameManifestEntry | None:
        return next(
            (
                e
                for e in self._store.manifest_entries.values()
                if e.product_id == product_id and e.entry_type == entry_type and e.is_current
            ),
            None,
        )


def install_fake_repositories(monkeypatch, store: LauncherContentFakeStore) -> None:
    monkeypatch.setattr(
        "services.launcher_content_service.LauncherNewsRepository",
        lambda session: FakeLauncherNewsRepository(session, store=store),
    )
    monkeypatch.setattr(
        "services.launcher_content_service.LauncherVersionRepository",
        lambda session: FakeLauncherVersionRepository(session, store=store),
    )
    monkeypatch.setattr(
        "services.launcher_content_service.GameManifestRepository",
        lambda session: FakeGameManifestRepository(session, store=store),
    )
