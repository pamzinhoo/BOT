from __future__ import annotations

import uuid

from sqlalchemy import select

from database.models.game_manifest import GameManifestEntry, ManifestEntryType
from database.repositories.base_repository import BaseRepository


class GameManifestRepository(BaseRepository[GameManifestEntry]):
    model = GameManifestEntry

    async def get_current(
        self, product_id: uuid.UUID, *, entry_type: ManifestEntryType = ManifestEntryType.FULL
    ) -> GameManifestEntry | None:
        result = await self.session.execute(
            select(GameManifestEntry).where(
                GameManifestEntry.product_id == product_id,
                GameManifestEntry.entry_type == entry_type,
                GameManifestEntry.is_current.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def set_current(self, product_id: uuid.UUID, entry: GameManifestEntry) -> None:
        """Garante no maximo 1 entrada `is_current=True` por product+tipo —
        desmarca a anterior antes de marcar a nova."""
        result = await self.session.execute(
            select(GameManifestEntry).where(
                GameManifestEntry.product_id == product_id,
                GameManifestEntry.entry_type == entry.entry_type,
                GameManifestEntry.is_current.is_(True),
            )
        )
        for previous in result.scalars().all():
            previous.is_current = False
        entry.is_current = True
        await self.session.flush()

    async def list_by_product(self, product_id: uuid.UUID) -> list[GameManifestEntry]:
        result = await self.session.execute(
            select(GameManifestEntry)
            .where(GameManifestEntry.product_id == product_id)
            .order_by(GameManifestEntry.created_at.desc())
        )
        return list(result.scalars().all())
