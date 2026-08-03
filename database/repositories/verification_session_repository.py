from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from database.models.verification_session import VerificationSession, VerificationSessionStatus
from database.repositories.base_repository import BaseRepository


class VerificationSessionRepository(BaseRepository[VerificationSession]):
    model = VerificationSession

    async def get_pending_by_guild_user(
        self, guild_id: int, user_id: int
    ) -> VerificationSession | None:
        result = await self.session.execute(
            select(VerificationSession).where(
                VerificationSession.guild_id == guild_id,
                VerificationSession.user_id == user_id,
                VerificationSession.status == VerificationSessionStatus.PENDING,
            )
        )
        return result.scalar_one_or_none()

    async def get_pending_by_guild_user_locked(
        self, guild_id: int, user_id: int
    ) -> VerificationSession | None:
        """Mesmo que get_pending_by_guild_user, mas com SELECT ... FOR UPDATE —
        evita que dois joins/retries quase simultaneos do mesmo usuario criem
        duas sessoes de verificacao em paralelo (race condition)."""
        result = await self.session.execute(
            select(VerificationSession)
            .where(
                VerificationSession.guild_id == guild_id,
                VerificationSession.user_id == user_id,
                VerificationSession.status == VerificationSessionStatus.PENDING,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_id_locked(self, session_id: uuid.UUID) -> VerificationSession | None:
        """SELECT ... FOR UPDATE pelo ID — usado ao processar uma tentativa
        (digitada ou por botao) pra impedir que dois cliques/submits
        concorrentes do mesmo captcha sejam processados ao mesmo tempo."""
        result = await self.session.execute(
            select(VerificationSession)
            .where(VerificationSession.id == session_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_expired_pending(self, before: datetime, limit: int = 200) -> list[VerificationSession]:
        result = await self.session.execute(
            select(VerificationSession)
            .where(
                VerificationSession.status == VerificationSessionStatus.PENDING,
                VerificationSession.expires_at <= before,
            )
            .limit(limit)
        )
        return list(result.scalars().all())
