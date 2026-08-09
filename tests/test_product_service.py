from __future__ import annotations

import uuid

import pytest

from database.models.product import ProductType
from services.product_service import ProductService
from tests._fakes_product import FakeDatabase, ProductFakeStore, install_fake_repositories


@pytest.fixture
def store() -> ProductFakeStore:
    return ProductFakeStore()


@pytest.fixture
def product_service(monkeypatch, store: ProductFakeStore) -> ProductService:
    install_fake_repositories(monkeypatch, store)
    return ProductService(FakeDatabase(store))


async def test_create_product(product_service: ProductService, store: ProductFakeStore) -> None:
    product = await product_service.create(
        slug="base-game", name="Base Game", product_type=ProductType.PERMANENT, price_amount=9990
    )

    assert product.slug == "base-game"
    assert product.is_active is True
    assert product.deleted_at is None
    assert len(store.products) == 1


async def test_update_product(product_service: ProductService) -> None:
    product = await product_service.create(slug="skin-fire", name="Skin Fogo", product_type=ProductType.COSMETIC)

    updated = await product_service.update(product.id, name="Skin de Fogo", price_amount=1990)

    assert updated is not None
    assert updated.name == "Skin de Fogo"
    assert updated.price_amount == 1990


async def test_update_unknown_product_returns_none(product_service: ProductService) -> None:
    assert await product_service.update(uuid.uuid4(), name="x") is None


async def test_soft_delete_hides_from_catalog(product_service: ProductService) -> None:
    product = await product_service.create(slug="wallpaper-1", name="Wallpaper 1", product_type=ProductType.COSMETIC)

    deleted = await product_service.soft_delete(product.id)

    assert deleted is not None
    assert deleted.is_active is False
    assert deleted.deleted_at is not None
    assert await product_service.get(product.id) is None
    assert await product_service.get(product.id, include_deleted=True) is not None


async def test_soft_delete_is_idempotent(product_service: ProductService) -> None:
    product = await product_service.create(slug="dlc-1", name="DLC 1", product_type=ProductType.DLC)
    first = await product_service.soft_delete(product.id)
    second = await product_service.soft_delete(product.id)

    assert first.deleted_at == second.deleted_at


async def test_list_catalog_only_active_by_default(product_service: ProductService) -> None:
    active = await product_service.create(slug="patrono", name="Patrono", product_type=ProductType.SUBSCRIPTION)
    inactive = await product_service.create(slug="mecenas", name="Mecenas", product_type=ProductType.SUBSCRIPTION)
    await product_service.soft_delete(inactive.id)

    catalog = await product_service.list_catalog()

    assert [p.id for p in catalog] == [active.id]


async def test_get_by_slug(product_service: ProductService) -> None:
    await product_service.create(slug="fundador", name="Fundador", product_type=ProductType.SUBSCRIPTION)

    found = await product_service.get_by_slug("fundador")
    missing = await product_service.get_by_slug("nao-existe")

    assert found is not None
    assert found.name == "Fundador"
    assert missing is None
