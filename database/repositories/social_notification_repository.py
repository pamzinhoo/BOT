from __future__ import annotations

from sqlalchemy import select

from database.models.social_notification import SocialNotification
from database.repositories.base_repository import BaseRepository


class SocialNotificationRepository(BaseRepository[SocialNotification]):
    model = SocialNotification

    async def list_by_guild(self, guild_id: int, limit: int = 50) -> list[SocialNotification]:
        result = await self.session.execute(
            select(SocialNotification)
            .where(SocialNotification.guild_id == guild_id)
            .order_by(SocialNotification.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_message(self, guild_id: int, message_id: int) -> SocialNotification | None:
        result = await self.session.execute(
            select(SocialNotification).where(
                SocialNotification.guild_id == guild_id,
                SocialNotification.message_id == message_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_fingerprint(
        self, guild_id: int, channel_id: int, url: str
    ) -> SocialNotification | None:
        result = await self.session.execute(
            select(SocialNotification)
            .where(
                SocialNotification.guild_id == guild_id,
                SocialNotification.channel_id == channel_id,
                SocialNotification.url == url,
                SocialNotification.status == "SENT",
            )
            .order_by(SocialNotification.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
