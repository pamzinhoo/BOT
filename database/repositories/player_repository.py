from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from database.models.player import Player
from database.repositories.base_repository import BaseRepository


class PlayerRepository(BaseRepository[Player]):
    model = Player

    async def get_by_discord_id(self, discord_id: int) -> Player | None:
        result = await self.session.execute(select(Player).where(Player.discord_id == discord_id))
        return result.scalar_one_or_none()

    async def list_by_ids(self, ids: list) -> list[Player]:
        """Batch de get_by_id — evita N+1 quando o chamador precisa resolver
        varios Player.id de uma vez (ex.: ReconciliationService resolvendo o
        player de cada License ativa de um product)."""
        if not ids:
            return []
        result = await self.session.execute(select(Player).where(Player.id.in_(ids)))
        return list(result.scalars().all())

    async def list_by_discord_ids(self, discord_ids: list[int]) -> list[Player]:
        """Batch de get_by_discord_id — evita N+1 quando o chamador precisa
        resolver varios discord_id de uma vez (ex.: ReconciliationService
        iterando membros de um cargo)."""
        if not discord_ids:
            return []
        result = await self.session.execute(select(Player).where(Player.discord_id.in_(discord_ids)))
        return list(result.scalars().all())

    async def get_or_create_by_discord_id(
        self, discord_id: int, *, discord_username: str | None, linked_at: datetime
    ) -> Player:
        """Upsert de login: cria o Player na primeira vez que o discord_id
        aparece, atualiza o username cacheado nas seguintes. Nunca cria mais
        de uma linha pro mesmo discord_id (unique constraint garante)."""
        player = await self.get_by_discord_id(discord_id)
        if player is None:
            player = Player(discord_id=discord_id, discord_username=discord_username, linked_at=linked_at)
            return await self.add(player)
        if discord_username is not None:
            player.discord_username = discord_username
        return player
