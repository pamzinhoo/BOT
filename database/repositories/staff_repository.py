from __future__ import annotations

from sqlalchemy import select

from database.models.staff import Staff
from database.repositories.base_repository import BaseRepository


class StaffRepository(BaseRepository[Staff]):
    model = Staff

    async def get_by_discord_id(self, guild_id: int, discord_user_id: int) -> Staff | None:
        result = await self.session.execute(
            select(Staff).where(
                Staff.guild_id == guild_id, Staff.discord_user_id == discord_user_id
            )
        )
        return result.scalar_one_or_none()
