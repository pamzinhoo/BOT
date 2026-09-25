from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from database.database import Database
from database.models.event_timer import EventTimer, EventTimerStatus
from database.repositories.event_timer_repository import EventTimerRepository
from providers.storage.base import StorageError, StorageProvider
from providers.storage.s3_compatible import S3CompatibleStorageProvider

if TYPE_CHECKING:
    from core.bot import LimerenceBot

_ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_MIN_REPEAT_SECONDS = 60


class EventTimerValidationError(ValueError):
    pass


class EventTimerService:
    def __init__(self, database: Database, bot: LimerenceBot) -> None:
        self._database = database
        self._bot = bot
        self._storage: StorageProvider | None = None
        settings = bot.settings
        if settings.storage_configured:
            self._storage = S3CompatibleStorageProvider(
                name=settings.storage_provider,
                bucket=settings.storage_bucket or "",
                access_key_id=settings.storage_access_key_id or "",
                secret_access_key=settings.storage_secret_access_key or "",
                endpoint_url=settings.storage_endpoint_url,
                region_name=settings.storage_region,
            )

    async def create(
        self,
        *,
        guild_id: int,
        creator_id: int,
        channel_id: int,
        title: str,
        description: str | None,
        ends_at: datetime,
        repeat_interval_seconds: int,
        mention_everyone: bool = True,
        image_bytes: bytes | None = None,
        image_filename: str | None = None,
        image_content_type: str | None = None,
    ) -> EventTimer:
        now = datetime.now(UTC)
        if ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=UTC)
        ends_at = ends_at.astimezone(UTC)
        if ends_at <= now:
            raise EventTimerValidationError("O encerramento precisa estar no futuro.")
        if repeat_interval_seconds < _MIN_REPEAT_SECONDS:
            raise EventTimerValidationError("O intervalo minimo e de 60 segundos.")
        clean_title = title.strip()
        if not clean_title:
            raise EventTimerValidationError("Titulo obrigatorio.")

        storage_path = None
        if image_bytes is not None:
            if self._storage is None:
                raise EventTimerValidationError("Storage de imagens nao esta configurado.")
            if image_content_type not in _ALLOWED_IMAGE_TYPES:
                raise EventTimerValidationError("Imagem deve ser PNG, JPG/JPEG ou WEBP.")
            if len(image_bytes) > _MAX_IMAGE_BYTES:
                raise EventTimerValidationError("Imagem excede 8 MB.")
            safe_name = PurePosixPath(image_filename or "evento.png").name
            storage_path = f"event-timers/{guild_id}/{uuid.uuid4()}-{safe_name}"
            await asyncio.to_thread(
                self._storage.upload_bytes,
                storage_path,
                image_bytes,
                content_type=image_content_type or "application/octet-stream",
            )
        try:
            async with self._database.session() as session:
                event = await EventTimerRepository(session).add(
                    EventTimer(
                        guild_id=guild_id,
                        creator_id=creator_id,
                        channel_id=channel_id,
                        title=clean_title[:256],
                        description=(description or "").strip() or None,
                        mention_everyone=mention_everyone,
                        repeat_interval_seconds=repeat_interval_seconds,
                        ends_at=ends_at,
                        next_announcement_at=now,
                        image_storage_path=storage_path,
                        image_filename=PurePosixPath(image_filename or "").name or None,
                        image_content_type=image_content_type,
                        image_size=len(image_bytes) if image_bytes is not None else None,
                    )
                )
                await session.refresh(event)
                return event
        except Exception:
            if storage_path and self._storage is not None:
                with contextlib.suppress(StorageError):
                    await asyncio.to_thread(self._storage.delete_object, storage_path)
            raise

    async def get(self, event_id: uuid.UUID) -> EventTimer | None:
        async with self._database.session() as session:
            return await EventTimerRepository(session).get_by_id(event_id)

    async def list_by_guild(self, guild_id: int) -> list[EventTimer]:
        async with self._database.session() as session:
            return await EventTimerRepository(session).list_by_guild(guild_id)

    async def list_due(self, now: datetime) -> list[EventTimer]:
        async with self._database.session() as session:
            return await EventTimerRepository(session).list_due(now)

    async def claim_due(self, event_id: uuid.UUID, now: datetime) -> EventTimer | None:
        async with self._database.session() as session:
            event = await EventTimerRepository(session).claim_due(event_id, now)
            if event is None:
                return None
            await session.refresh(event)
            return event

    async def list_expired(self, now: datetime) -> list[EventTimer]:
        async with self._database.session() as session:
            return await EventTimerRepository(session).list_expired(now)

    async def mark_announced(self, event_id: uuid.UUID, message_id: int, when: datetime) -> None:
        async with self._database.session() as session:
            event = await EventTimerRepository(session).get_by_id_locked(event_id)
            if event is None or event.status != EventTimerStatus.ACTIVE:
                return
            event.message_id = message_id
            event.last_announcement_at = when
            event.last_error = None
            await session.flush()

    async def mark_error(self, event_id: uuid.UUID, message: str) -> None:
        async with self._database.session() as session:
            event = await EventTimerRepository(session).get_by_id(event_id)
            if event is None:
                return
            event.last_error = message[:1000]
            await session.flush()

    async def pause(self, event_id: uuid.UUID) -> EventTimer | None:
        async with self._database.session() as session:
            event = await EventTimerRepository(session).get_by_id_locked(event_id)
            if event is None or event.status != EventTimerStatus.ACTIVE:
                return None
            event.status = EventTimerStatus.PAUSED
            event.next_announcement_at = None
            await session.flush()
            await session.refresh(event)
            return event

    async def resume(self, event_id: uuid.UUID) -> EventTimer | None:
        now = datetime.now(UTC)
        async with self._database.session() as session:
            event = await EventTimerRepository(session).get_by_id_locked(event_id)
            if event is None or event.status != EventTimerStatus.PAUSED or event.ends_at <= now:
                return None
            event.status = EventTimerStatus.ACTIVE
            event.next_announcement_at = now
            await session.flush()
            await session.refresh(event)
            return event

    async def finish(self, event_id: uuid.UUID, *, canceled: bool = False) -> EventTimer | None:
        async with self._database.session() as session:
            event = await EventTimerRepository(session).get_by_id_locked(event_id)
            if event is None or event.status in {
                EventTimerStatus.FINISHED,
                EventTimerStatus.CANCELED,
            }:
                return event
            event.status = EventTimerStatus.CANCELED if canceled else EventTimerStatus.FINISHED
            event.finished_at = datetime.now(UTC)
            event.next_announcement_at = None
            if event.image_storage_path:
                event.image_delete_pending = True
            await session.flush()
            await session.refresh(event)
        await self.cleanup_image(event.id)
        return event

    async def cleanup_image(self, event_id: uuid.UUID) -> bool:
        event = await self.get(event_id)
        if event is None or not event.image_storage_path:
            return True
        if self._storage is None:
            return False
        try:
            await asyncio.to_thread(self._storage.delete_object, event.image_storage_path)
        except StorageError:
            return False
        async with self._database.session() as session:
            current = await EventTimerRepository(session).get_by_id(event_id)
            if current is None:
                return True
            current.image_storage_path = None
            current.image_filename = None
            current.image_content_type = None
            current.image_size = None
            current.image_delete_pending = False
            await session.flush()
        return True

    async def retry_pending_image_cleanup(self) -> None:
        async with self._database.session() as session:
            items = await EventTimerRepository(session).list_image_cleanup_pending()
        for item in items:
            await self.cleanup_image(item.id)

    async def load_image(self, event: EventTimer) -> bytes | None:
        if not event.image_storage_path:
            return None
        if self._storage is None:
            raise StorageError("Storage de imagens nao esta configurado.")
        return await asyncio.to_thread(self._storage.download_bytes, event.image_storage_path)
