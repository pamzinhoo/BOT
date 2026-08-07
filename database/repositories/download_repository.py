from __future__ import annotations

import uuid

from sqlalchemy import select

from database.models.download import Download
from database.repositories.base_repository import BaseRepository


class DownloadRepository(BaseRepository[Download]):
    model = Download

    async def list_by_player(self, player_id: uuid.UUID, *, limit: int = 50) -> list[Download]:
        result = await self.session.execute(
            select(Download)
            .where(Download.player_id == player_id)
            .order_by(Download.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
