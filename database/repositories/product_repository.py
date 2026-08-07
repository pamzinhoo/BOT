from __future__ import annotations

import uuid

from sqlalchemy import select

from database.models.product import Product
from database.repositories.base_repository import BaseRepository


class ProductRepository(BaseRepository[Product]):
    model = Product

    async def get_by_id(self, id_: uuid.UUID, *, include_deleted: bool = False) -> Product | None:
        product = await self.session.get(Product, id_)
        if product is not None and product.deleted_at is not None and not include_deleted:
            return None
        return product

    async def get_by_slug(self, slug: str, *, include_deleted: bool = False) -> Product | None:
        stmt = select(Product).where(Product.slug == slug)
        if not include_deleted:
            stmt = stmt.where(Product.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_catalog(self, *, only_active: bool = True) -> list[Product]:
        stmt = select(Product).where(Product.deleted_at.is_(None))
        if only_active:
            stmt = stmt.where(Product.is_active.is_(True))
        stmt = stmt.order_by(Product.position.asc(), Product.name.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
