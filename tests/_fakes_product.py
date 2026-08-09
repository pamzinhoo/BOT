"""Duplas de teste (fakes) pro ProductService — mesmo padrao de
tests/_fakes_license.py."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from database.models.product import Product


@dataclass
class ProductFakeStore:
    products: dict[uuid.UUID, Product] = field(default_factory=dict)


class FakeSession:
    async def flush(self) -> None:
        pass

    async def refresh(self, entity: object) -> None:
        pass


class FakeDatabase:
    def __init__(self, store: ProductFakeStore) -> None:
        self.store = store

    @asynccontextmanager
    async def session(self):
        yield FakeSession()


def _new_id(entity: object) -> None:
    if getattr(entity, "id", None) is None:
        entity.id = uuid.uuid4()


class FakeProductRepository:
    def __init__(self, session: FakeSession, *, store: ProductFakeStore) -> None:
        self._store = store

    async def add(self, entity: Product) -> Product:
        _new_id(entity)
        self._store.products[entity.id] = entity
        return entity

    async def get_by_id(self, id_: uuid.UUID, *, include_deleted: bool = False) -> Product | None:
        product = self._store.products.get(id_)
        if product is not None and product.deleted_at is not None and not include_deleted:
            return None
        return product

    async def get_by_slug(self, slug: str, *, include_deleted: bool = False) -> Product | None:
        for product in self._store.products.values():
            if product.slug == slug and (include_deleted or product.deleted_at is None):
                return product
        return None

    async def list_catalog(self, *, only_active: bool = True) -> list[Product]:
        items = [p for p in self._store.products.values() if p.deleted_at is None]
        if only_active:
            items = [p for p in items if p.is_active]
        return sorted(items, key=lambda p: (p.position, p.name))


def install_fake_repositories(monkeypatch, store: ProductFakeStore) -> None:
    monkeypatch.setattr(
        "services.product_service.ProductRepository",
        lambda session: FakeProductRepository(session, store=store),
    )
