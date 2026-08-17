from __future__ import annotations

import uuid

from sqlalchemy import select

from database.models.product import Product, ProductType
from database.repositories.base_repository import BaseRepository


class ProductRepository(BaseRepository[Product]):
    model = Product

    async def get_by_id(self, id_: uuid.UUID, *, include_deleted: bool = False) -> Product | None:
        product = await self.session.get(Product, id_)
        if product is not None and product.deleted_at is not None and not include_deleted:
            return None
        return product

    async def list_by_ids(self, ids: list[uuid.UUID], *, include_deleted: bool = False) -> list[Product]:
        """Batch de get_by_id — evita 1 query por Product quando o chamador
        ja tem a lista inteira de ids (ex.: /player/licenses resolvendo o
        Product de cada License de uma vez)."""
        if not ids:
            return []
        stmt = select(Product).where(Product.id.in_(ids))
        if not include_deleted:
            stmt = stmt.where(Product.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

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

    async def list_dlc(self, *, only_active: bool = False) -> list[Product]:
        stmt = select(Product).where(Product.deleted_at.is_(None), Product.product_type == ProductType.DLC)
        if only_active:
            stmt = stmt.where(Product.is_active.is_(True))
        stmt = stmt.order_by(Product.position.asc(), Product.name.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_free_dlc_by_guild(self, guild_id: int) -> list[Product]:
        """DLC gratuita (product_type=DLC, sem preco) cujo cargo obrigatorio
        vive nesta guild — base do listener de member_update e da
        reconciliacao periodica (services/dlc_service.py)."""
        result = await self.session.execute(
            select(Product).where(
                Product.deleted_at.is_(None),
                Product.is_active.is_(True),
                Product.product_type == ProductType.DLC,
                Product.required_role_guild_id == guild_id,
                Product.required_role_id.is_not(None),
            )
        )
        return list(result.scalars().all())
