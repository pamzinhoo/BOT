from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from database.models.game_manifest import GameManifestEntry, ManifestEntryType
from database.models.launcher_news import LauncherNews
from database.models.launcher_version import LauncherPlatform, LauncherVersion
from services.launcher_content_service import LauncherContentService
from tests._fakes_launcher_content import (
    FakeDatabase,
    LauncherContentFakeStore,
    install_fake_repositories,
)


@pytest.fixture
def store() -> LauncherContentFakeStore:
    return LauncherContentFakeStore()


@pytest.fixture
def content_service(monkeypatch, store: LauncherContentFakeStore) -> LauncherContentService:
    install_fake_repositories(monkeypatch, store)
    return LauncherContentService(FakeDatabase(store))


async def test_list_news_only_published(content_service: LauncherContentService, store: LauncherContentFakeStore) -> None:
    published = LauncherNews(title="Novidade", content="...", is_published=True, published_at=datetime.now(UTC))
    published.id = uuid.uuid4()
    published.deleted_at = None
    draft = LauncherNews(title="Rascunho", content="...", is_published=False, published_at=None)
    draft.id = uuid.uuid4()
    draft.deleted_at = None
    store.news.extend([published, draft])

    result = await content_service.list_news()

    assert [n.id for n in result] == [published.id]


async def test_get_launcher_version_returns_current(
    content_service: LauncherContentService, store: LauncherContentFakeStore
) -> None:
    version = LauncherVersion(
        version="1.0.0", platform=LauncherPlatform.WINDOWS, sha256="a" * 64, size_bytes=100,
        storage_path="launcher/windows/1.0.0.pkg", is_current=True,
    )
    version.id = uuid.uuid4()
    store.versions[LauncherPlatform.WINDOWS] = version

    result = await content_service.get_launcher_version(LauncherPlatform.WINDOWS)
    assert result is not None
    assert result.version == "1.0.0"

    missing = await content_service.get_launcher_version(LauncherPlatform.MACOS)
    assert missing is None


async def test_get_manifest_returns_current_entry(
    content_service: LauncherContentService, store: LauncherContentFakeStore
) -> None:
    product_id = uuid.uuid4()
    entry = GameManifestEntry(
        product_id=product_id, version="2.0.0", sha256="c" * 64, size_bytes=500,
        storage_path=f"products/{product_id}/2.0.0.pkg", entry_type=ManifestEntryType.FULL,
        depends_on=[], is_current=True,
    )
    entry.id = uuid.uuid4()
    store.manifest_entries[entry.id] = entry

    result = await content_service.get_manifest(product_id)
    assert result is not None
    assert result.version == "2.0.0"

    missing = await content_service.get_manifest(uuid.uuid4())
    assert missing is None
