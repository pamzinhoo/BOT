from __future__ import annotations

import uuid
from datetime import UTC, datetime

from database.database import Database
from database.models.product import Product, ProductType
from database.repositories.product_repository import ProductRepository


class ProductService:
    """CRUD do catalogo generico de Products (base game, DLC, cosmetico,
    pacotes de assinatura...). Exclusao e sempre soft (is_active=False +
    deleted_at) — License referencia Product com FK RESTRICT, entao apagar a
    linha de verdade quebraria o historico de posse de quem ja comprou."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def create(
        self,
        *,
        slug: str,
        name: str,
        product_type: ProductType,
        description: str | None = None,
        price_amount: int | None = None,
        currency: str = "BRL",
        position: int = 0,
        created_by_staff_id: int | None = None,
    ) -> Product:
        async with self._database.session() as session:
            return await ProductRepository(session).add(
                Product(
                    slug=slug,
                    name=name,
                    product_type=product_type,
                    description=description,
                    price_amount=price_amount,
                    currency=currency,
                    position=position,
                    is_active=True,
                    created_by_staff_id=created_by_staff_id,
                )
            )

    async def update(self, product_id: uuid.UUID, **fields: object) -> Product | None:
        async with self._database.session() as session:
            repo = ProductRepository(session)
            product = await repo.get_by_id(product_id)
            if product is None:
                return None
            for key, value in fields.items():
                setattr(product, key, value)
            await session.flush()
            await session.refresh(product)
            return product

    async def soft_delete(self, product_id: uuid.UUID) -> Product | None:
        """Idempotente: repete a chamada num Product ja desativado sem efeito
        colateral (deleted_at nao muda de novo)."""
        async with self._database.session() as session:
            repo = ProductRepository(session)
            product = await repo.get_by_id(product_id, include_deleted=True)
            if product is None or product.deleted_at is not None:
                return product
            product.is_active = False
            product.deleted_at = datetime.now(UTC)
            await session.flush()
            await session.refresh(product)
            return product

    async def get(self, product_id: uuid.UUID, *, include_deleted: bool = False) -> Product | None:
        async with self._database.session() as session:
            return await ProductRepository(session).get_by_id(product_id, include_deleted=include_deleted)

    async def list_by_ids(self, product_ids: list[uuid.UUID], *, include_deleted: bool = False) -> list[Product]:
        async with self._database.session() as session:
            return await ProductRepository(session).list_by_ids(product_ids, include_deleted=include_deleted)

    async def get_by_slug(self, slug: str, *, include_deleted: bool = False) -> Product | None:
        async with self._database.session() as session:
            return await ProductRepository(session).get_by_slug(slug, include_deleted=include_deleted)

    async def list_catalog(self, *, only_active: bool = True) -> list[Product]:
        async with self._database.session() as session:
            return await ProductRepository(session).list_catalog(only_active=only_active)
