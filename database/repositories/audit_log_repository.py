from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, or_, select

from database.models.audit_log import AuditLogCategory, AuditLogEntry
from database.repositories.base_repository import BaseRepository


def _apply_filters(
    query,
    *,
    guild_id: int,
    target_id: int | None,
    executor_id: int | None,
    category: AuditLogCategory | None,
    action: str | None,
    config_category: str | None,
    config_name: str | None,
    search: str | None,
    since: datetime | None,
):
    query = query.where(AuditLogEntry.guild_id == guild_id)
    if target_id is not None:
        query = query.where(AuditLogEntry.target_id == target_id)
    if executor_id is not None:
        query = query.where(AuditLogEntry.executor_id == executor_id)
    if category is not None:
        query = query.where(AuditLogEntry.category == category)
    if action is not None:
        query = query.where(AuditLogEntry.action.ilike(f"%{action}%"))
    if config_category is not None:
        query = query.where(AuditLogEntry.config_category == config_category)
    if config_name is not None:
        for word in config_name.split():
            query = query.where(AuditLogEntry.config_name.ilike(f"%{word}%"))
    if search:
        terms = [
            AuditLogEntry.action.ilike(f"%{search}%"),
            AuditLogEntry.executor_name.ilike(f"%{search}%"),
            AuditLogEntry.target_name.ilike(f"%{search}%"),
            AuditLogEntry.reason.ilike(f"%{search}%"),
            AuditLogEntry.config_category.ilike(f"%{search}%"),
            AuditLogEntry.config_name.ilike(f"%{search}%"),
        ]
        try:
            parsed = int(search)
        except ValueError:
            parsed = None
        if parsed is not None:
            terms.extend([AuditLogEntry.executor_id == parsed, AuditLogEntry.target_id == parsed])
        query = query.where(or_(*terms))
    if since is not None:
        query = query.where(AuditLogEntry.created_at >= since)
    return query


class AuditLogRepository(BaseRepository[AuditLogEntry]):
    model = AuditLogEntry

    async def list_filtered(
        self,
        guild_id: int,
        *,
        target_id: int | None = None,
        executor_id: int | None = None,
        category: AuditLogCategory | None = None,
        action: str | None = None,
        config_category: str | None = None,
        config_name: str | None = None,
        search: str | None = None,
        since: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[AuditLogEntry]:
        query = _apply_filters(
            select(AuditLogEntry),
            guild_id=guild_id,
            target_id=target_id,
            executor_id=executor_id,
            category=category,
            action=action,
            config_category=config_category,
            config_name=config_name,
            search=search,
            since=since,
        )
        query = query.order_by(AuditLogEntry.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def count_filtered(
        self,
        guild_id: int,
        *,
        target_id: int | None = None,
        executor_id: int | None = None,
        category: AuditLogCategory | None = None,
        action: str | None = None,
        config_category: str | None = None,
        config_name: str | None = None,
        search: str | None = None,
        since: datetime | None = None,
    ) -> int:
        query = _apply_filters(
            select(func.count()).select_from(AuditLogEntry),
            guild_id=guild_id,
            target_id=target_id,
            executor_id=executor_id,
            category=category,
            action=action,
            config_category=config_category,
            config_name=config_name,
            search=search,
            since=since,
        )
        result = await self.session.execute(query)
        return int(result.scalar_one())

    async def get_for_guild(self, guild_id: int, entry_id: uuid.UUID) -> AuditLogEntry | None:
        result = await self.session.execute(
            select(AuditLogEntry).where(
                AuditLogEntry.guild_id == guild_id,
                AuditLogEntry.id == entry_id,
            )
        )
        return result.scalar_one_or_none()
