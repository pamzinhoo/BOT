from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI

from api.dependencies import get_current_player
from api.routes.download_routes import router as download_router
from api.routes.launcher_routes import router as launcher_router
from api.routes.player_routes import router as player_router
from database.models.game_manifest import GameManifestEntry, ManifestEntryType
from database.models.launcher_news import LauncherNews
from database.models.launcher_version import LauncherPlatform, LauncherVersion
from database.models.player import Player
from database.models.product import ProductType
from services.download_service import DownloadService
from services.launcher_content_service import LauncherContentService
from services.license_service import LicenseService
from services.product_service import ProductService
from tests._fakes_download import DownloadFakeStore, FakeStorageProvider
from tests._fakes_download import FakeDatabase as DownloadFakeDatabase
from tests._fakes_download import install_fake_repositories as install_download_fakes
from tests._fakes_launcher_content import (
    FakeDatabase as ContentFakeDatabase,
)
from tests._fakes_launcher_content import (
    LauncherContentFakeStore,
)
from tests._fakes_launcher_content import (
    install_fake_repositories as install_content_fakes,
)
from tests._fakes_license import FakeDatabase as LicenseFakeDatabase
from tests._fakes_license import LicenseFakeStore
from tests._fakes_license import install_fake_repositories as install_license_fakes
from tests._fakes_product import FakeDatabase as ProductFakeDatabase
from tests._fakes_product import ProductFakeStore
from tests._fakes_product import install_fake_repositories as install_product_fakes


class _FakeSettings:
    storage_download_ttl_seconds = 600


def _player() -> Player:
    player = Player(discord_id=42, discord_username="tester", linked_at=datetime.now(UTC))
    player.id = uuid.uuid4()
    return player


@pytest.fixture
def stores(monkeypatch):
    download_store = DownloadFakeStore()
    license_store = LicenseFakeStore()
    product_store = ProductFakeStore()
    content_store = LauncherContentFakeStore()

    install_download_fakes(monkeypatch, download_store)
    install_license_fakes(monkeypatch, license_store)
    install_product_fakes(monkeypatch, product_store)
    install_content_fakes(monkeypatch, content_store)

    return download_store, license_store, product_store, content_store


@pytest.fixture
def player() -> Player:
    return _player()


@pytest.fixture
def storage() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
def client(stores, player: Player, storage: FakeStorageProvider):
    download_store, license_store, product_store, content_store = stores
    license_service = LicenseService(LicenseFakeDatabase(license_store))
    product_service = ProductService(ProductFakeDatabase(product_store))

    app = FastAPI()
    app.state.license_service = license_service
    app.state.product_service = product_service
    app.state.launcher_content_service = LauncherContentService(ContentFakeDatabase(content_store))
    app.state.download_service = DownloadService(
        DownloadFakeDatabase(download_store), license_service, storage, _FakeSettings()
    )
    app.include_router(launcher_router)
    app.include_router(player_router)
    app.include_router(download_router)
    app.dependency_overrides[get_current_player] = lambda: player

    transport = httpx.ASGITransport(app=app)
    http_client = httpx.AsyncClient(transport=transport, base_url="http://test")
    http_client.app = app  # type: ignore[attr-defined]
    http_client.license_service = license_service  # type: ignore[attr-defined]
    http_client.download_store = download_store  # type: ignore[attr-defined]
    http_client.content_store = content_store  # type: ignore[attr-defined]
    return http_client


def _seed_manifest(store: DownloadFakeStore, product_id: uuid.UUID, *, sha256: str = "a" * 64) -> GameManifestEntry:
    entry = GameManifestEntry(
        product_id=product_id, version="1.0.0", sha256=sha256, size_bytes=1024,
        storage_path=f"products/{product_id}/1.0.0.pkg", entry_type=ManifestEntryType.FULL,
        depends_on=[], is_current=True,
    )
    entry.id = uuid.uuid4()
    store.manifest_entries[entry.id] = entry
    return entry


async def test_download_requires_license(client: httpx.AsyncClient) -> None:
    async with client as c:
        r = await c.post("/download", json={"product_id": str(uuid.uuid4())})
        assert r.status_code == 403
        assert r.json()["detail"]["error"] == "license_required"


async def test_download_success(client: httpx.AsyncClient, player: Player) -> None:
    product_id = uuid.uuid4()
    await client.license_service.grant_or_renew(player.id, product_id, purchase_source="loja")
    _seed_manifest(client.download_store, product_id)

    async with client as c:
        r = await c.post("/download", json={"product_id": str(product_id)})
        assert r.status_code == 200
        body = r.json()
        assert body["sha256"] == "a" * 64
        assert body["url"].startswith("https://fake-storage.example/")

        complete = await c.post(
            f"/download/{body['download_id']}/complete", json={"client_sha256": "a" * 64}
        )
        assert complete.status_code == 200
        assert complete.json()["status"] == "completed"


async def test_download_complete_checksum_mismatch(client: httpx.AsyncClient, player: Player) -> None:
    product_id = uuid.uuid4()
    await client.license_service.grant_or_renew(player.id, product_id, purchase_source="loja")
    _seed_manifest(client.download_store, product_id)

    async with client as c:
        r = await c.post("/download", json={"product_id": str(product_id)})
        download_id = r.json()["download_id"]

        complete = await c.post(f"/download/{download_id}/complete", json={"client_sha256": "f" * 64})
        assert complete.status_code == 200
        assert complete.json()["status"] == "failed"
        assert complete.json()["failure_reason"] == "checksum_mismatch"


async def test_update_requires_valid_platform(client: httpx.AsyncClient) -> None:
    async with client as c:
        r = await c.post("/update", json={"platform": "amiga"})
        assert r.status_code == 400
        assert r.json()["detail"]["error"] == "invalid_platform"


async def test_update_no_auth_required(client: httpx.AsyncClient) -> None:
    async with client as c:
        r = await c.post("/update", json={"platform": "windows"})
        assert r.status_code == 404
        assert r.json()["detail"]["error"] == "version_not_found"


async def test_launcher_news_is_public(client: httpx.AsyncClient) -> None:
    news_item = LauncherNews(title="Oi", content="...", is_published=True, published_at=datetime.now(UTC))
    news_item.id = uuid.uuid4()
    news_item.deleted_at = None
    client.content_store.news.append(news_item)

    async with client as c:
        r = await c.get("/launcher/news")
        assert r.status_code == 200
        assert len(r.json()) == 1


async def test_launcher_version_public(client: httpx.AsyncClient) -> None:
    version_row = LauncherVersion(
        version="1.0.0", platform=LauncherPlatform.WINDOWS, sha256="b" * 64, size_bytes=10,
        storage_path="launcher/windows/1.0.0.pkg", is_current=True, is_mandatory=False,
    )
    version_row.id = uuid.uuid4()
    client.content_store.versions[LauncherPlatform.WINDOWS] = version_row

    async with client as c:
        r = await c.get("/launcher/version?platform=windows")
        assert r.status_code == 200
        assert r.json()["version"] == "1.0.0"


async def test_launcher_manifest_requires_license(client: httpx.AsyncClient) -> None:
    product_id = uuid.uuid4()
    entry = GameManifestEntry(
        product_id=product_id, version="1.0.0", sha256="c" * 64, size_bytes=10,
        storage_path="x", entry_type=ManifestEntryType.FULL, depends_on=[], is_current=True,
    )
    entry.id = uuid.uuid4()
    client.content_store.manifest_entries[entry.id] = entry

    async with client as c:
        r = await c.get(f"/launcher/manifest?product_id={product_id}")
        assert r.status_code == 403
        assert r.json()["detail"]["error"] == "license_required"


async def test_player_products_reflects_ownership(client: httpx.AsyncClient, player: Player) -> None:
    product_service: ProductService = client.app.state.product_service
    owned = await product_service.create(slug="owned-product", name="Owned", product_type=ProductType.COSMETIC)
    await product_service.create(slug="not-owned", name="Not Owned", product_type=ProductType.COSMETIC)
    await client.license_service.grant_or_renew(player.id, owned.id, purchase_source="loja")

    async with client as c:
        r = await c.get("/player/products")
        assert r.status_code == 200
        by_slug = {p["slug"]: p for p in r.json()}
        assert by_slug["owned-product"]["owned"] is True
        assert by_slug["not-owned"]["owned"] is False


async def test_download_rate_limit_is_enforced(client: httpx.AsyncClient, player: Player) -> None:
    """Fase 6: /download nao tinha nenhum rate limit — confirma que o limite
    (30 req/300s por player, api/routes/download_routes.py) de fato dispara
    429 pelo HTTP, nao so na unidade do RateLimiter."""
    product_id = uuid.uuid4()
    await client.license_service.grant_or_renew(player.id, product_id, purchase_source="loja")
    _seed_manifest(client.download_store, product_id)

    async with client as c:
        responses = [await c.post("/download", json={"product_id": str(product_id)}) for _ in range(31)]

    assert responses[-1].status_code == 429
    assert responses[-1].json()["detail"]["error"] == "rate_limited"
    assert "Retry-After" in responses[-1].headers
    assert all(r.status_code == 200 for r in responses[:30])
