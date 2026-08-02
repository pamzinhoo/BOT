from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from database.models.subscription_renewal import (
    SubscriptionMessage,
    SubscriptionMessageType,
    SubscriptionReminder,
    SubscriptionReminderDay,
    SubscriptionRenewalButton,
    SubscriptionRenewalButtonKey,
    SubscriptionRenewalSettings,
)
from database.repositories.base_repository import BaseRepository


class SubscriptionRenewalSettingsRepository(BaseRepository[SubscriptionRenewalSettings]):
    model = SubscriptionRenewalSettings

    async def get_by_guild_id(self, guild_id: int) -> SubscriptionRenewalSettings | None:
        result = await self.session.execute(
            select(SubscriptionRenewalSettings).where(
                SubscriptionRenewalSettings.guild_id == guild_id
            )
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, guild_id: int) -> SubscriptionRenewalSettings:
        settings = await self.get_by_guild_id(guild_id)
        if settings is not None:
            return settings
        return await self.add(SubscriptionRenewalSettings(guild_id=guild_id))

    async def list_enabled(self) -> list[SubscriptionRenewalSettings]:
        """Unico list sem guild_id: o scheduler precisa varrer todas as guilds
        com renovacao ligada. Cada linha ja carrega o proprio guild_id e todo o
        processamento seguinte e feito guild a guild."""
        result = await self.session.execute(
            select(SubscriptionRenewalSettings).where(SubscriptionRenewalSettings.enabled.is_(True))
        )
        return list(result.scalars().all())


class SubscriptionReminderDayRepository(BaseRepository[SubscriptionReminderDay]):
    model = SubscriptionReminderDay

    async def list_by_guild(self, guild_id: int) -> list[SubscriptionReminderDay]:
        result = await self.session.execute(
            select(SubscriptionReminderDay)
            .where(SubscriptionReminderDay.guild_id == guild_id)
            .order_by(
                SubscriptionReminderDay.position.asc(), SubscriptionReminderDay.days_before.desc()
            )
        )
        return list(result.scalars().all())

    async def get_by_days_before(
        self, guild_id: int, days_before: int
    ) -> SubscriptionReminderDay | None:
        result = await self.session.execute(
            select(SubscriptionReminderDay).where(
                SubscriptionReminderDay.guild_id == guild_id,
                SubscriptionReminderDay.days_before == days_before,
            )
        )
        return result.scalar_one_or_none()


class SubscriptionMessageRepository(BaseRepository[SubscriptionMessage]):
    model = SubscriptionMessage

    async def get_by_guild_and_type(
        self, guild_id: int, message_type: SubscriptionMessageType
    ) -> SubscriptionMessage | None:
        result = await self.session.execute(
            select(SubscriptionMessage).where(
                SubscriptionMessage.guild_id == guild_id,
                SubscriptionMessage.message_type == message_type,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_guild(self, guild_id: int) -> list[SubscriptionMessage]:
        result = await self.session.execute(
            select(SubscriptionMessage).where(SubscriptionMessage.guild_id == guild_id)
        )
        return list(result.scalars().all())


class SubscriptionRenewalButtonRepository(BaseRepository[SubscriptionRenewalButton]):
    model = SubscriptionRenewalButton

    async def list_by_guild(self, guild_id: int) -> list[SubscriptionRenewalButton]:
        result = await self.session.execute(
            select(SubscriptionRenewalButton)
            .where(SubscriptionRenewalButton.guild_id == guild_id)
            .order_by(SubscriptionRenewalButton.position.asc())
        )
        return list(result.scalars().all())

    async def get_by_key(
        self, guild_id: int, key: SubscriptionRenewalButtonKey
    ) -> SubscriptionRenewalButton | None:
        result = await self.session.execute(
            select(SubscriptionRenewalButton).where(
                SubscriptionRenewalButton.guild_id == guild_id,
                SubscriptionRenewalButton.key == key,
            )
        )
        return result.scalar_one_or_none()


class SubscriptionReminderRepository(BaseRepository[SubscriptionReminder]):
    model = SubscriptionReminder

    async def exists(
        self,
        subscription_id: uuid.UUID,
        reminder_type: str,
        period_end: datetime | None,
    ) -> bool:
        """Checagem persistida de idempotencia — chamada antes de TODO envio,
        pra o mesmo lembrete nunca sair duas vezes (inclusive apos restart)."""
        stmt = select(SubscriptionReminder.id).where(
            SubscriptionReminder.subscription_id == subscription_id,
            SubscriptionReminder.reminder_type == reminder_type,
        )
        stmt = stmt.where(
            SubscriptionReminder.period_end.is_(None)
            if period_end is None
            else SubscriptionReminder.period_end == period_end
        )
        result = await self.session.execute(stmt.limit(1))
        return result.scalar_one_or_none() is not None

    async def reserve(
        self,
        *,
        guild_id: int,
        subscription_id: uuid.UUID,
        reminder_type: str,
        period_end: datetime | None,
        now: datetime,
    ) -> uuid.UUID | None:
        """Grava a linha do lembrete ANTES de enviar o DM (status 'pending'),
        pra que um crash entre o envio e o registro nao cause reenvio na
        proxima passada do scheduler — a UniqueConstraint tambem torna isto
        seguro contra duas execucoes concorrentes do scheduler. Retorna None
        se a linha ja existir (outro processo reservou primeiro)."""
        reminder = SubscriptionReminder(
            guild_id=guild_id,
            subscription_id=subscription_id,
            reminder_type=reminder_type,
            period_end=period_end,
            sent_at=now,
            delivery_status="pending",
        )
        self.session.add(reminder)
        try:
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            return None
        return reminder.id

    async def finalize(self, reminder_id: uuid.UUID, *, delivery_status: str) -> None:
        reminder = await self.session.get(SubscriptionReminder, reminder_id)
        if reminder is not None:
            reminder.delivery_status = delivery_status

    async def list_by_subscription(self, subscription_id: uuid.UUID) -> list[SubscriptionReminder]:
        result = await self.session.execute(
            select(SubscriptionReminder)
            .where(SubscriptionReminder.subscription_id == subscription_id)
            .order_by(SubscriptionReminder.sent_at.desc())
        )
        return list(result.scalars().all())

    async def list_by_guild(self, guild_id: int) -> list[SubscriptionReminder]:
        result = await self.session.execute(
            select(SubscriptionReminder)
            .where(SubscriptionReminder.guild_id == guild_id)
            .order_by(SubscriptionReminder.sent_at.desc())
        )
        return list(result.scalars().all())
