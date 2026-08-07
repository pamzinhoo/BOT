from __future__ import annotations

import uuid

from sqlalchemy import select

from database.models.download import Download
from database.repositories.base_repository import BaseRepository


class DownloadRepository(BaseRepository[Download]):
    model = Download

    async def get_by_id_locked(self, download_id: uuid.UUID) -> Download | None:
        """Mesmo padrao de PaymentRepository/LicenseRepository.get_by_id_locked
        — trava a linha ate o fim da transacao, pra dois POST /download/{id}/
        complete concorrentes (retry do Launcher) nao correrem pra decidir
        COMPLETED/FAILED ao mesmo tempo sobre o mesmo download."""
        result = await self.session.execute(
            select(Download).where(Download.id == download_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_by_player(self, player_id: uuid.UUID, *, limit: int = 50) -> list[Download]:
        result = await self.session.execute(
            select(Download)
            .where(Download.player_id == player_id)
            .order_by(Download.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
