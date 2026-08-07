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
