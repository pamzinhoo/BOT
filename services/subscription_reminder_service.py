from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import discord

from core.logger import get_logger
from database.database import Database
from database.models.audit_log import AuditLogCategory
from database.models.plan import Plan
from database.models.subscription import Subscription
from database.models.subscription_renewal import (
    SubscriptionMessageType,
    SubscriptionReminder,
    SubscriptionRenewalSettings,
)
from database.repositories.plan_repository import PlanRepository
from database.repositories.subscription_renewal_repository import (
    SubscriptionReminderRepository,
)
from database.repositories.subscription_repository import SubscriptionRepository
from services.plan_service import render_placeholders
from services.subscription_renewal_config_service import SubscriptionRenewalConfigService
from services.subscription_service import SubscriptionService

if TYPE_CHECKING:
    from core.bot import LimerenceBot

logger = get_logger("subscription_reminder_service")

# chaves do livro-razao (SubscriptionReminder.reminder_type)
REMINDER_DAY_PREFIX = "day_"
REMINDER_TYPE_EXPIRED = "expired"
REMINDER_TYPE_GRACE_STARTED = "grace_started"
REMINDER_TYPE_GRACE_FINISHED = "grace_finished"
REMINDER_TYPE_RENEWED = "renewed"

DELIVERY_SENT = "sent"
DELIVERY_FAILED = "failed"
DELIVERY_SKIPPED = "skipped"


def days_left_until(period_end: datetime, now: datetime) -> int:
    """Dias inteiros que faltam pro vencimento, arredondando pra cima: enquanto
    faltar qualquer fração do 7º dia o resultado é 7. Assim um aviso de "7 dias
    antes" dispara na primeira passada dentro dessa janela, mesmo que o ciclo de
    checagem rode só uma vez por dia."""
    delta = period_end - now
    return math.ceil(delta.total_seconds() / 86400)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@dataclass(frozen=True)
class _Delivery:
    status: str


class SubscriptionReminderService:
    """Cérebro do sistema de renovação de assinaturas: avisa antes do
    vencimento, aplica carência, expira e remove benefícios — tudo no ritmo e
    com os textos que cada guild configurou. As Cogs só chamam
    `run_check_cycle`, nenhuma regra de negócio vive nelas.

    Nunca fala com gateway de pagamento: o botão "Renovar" das mensagens
    reaproveita o fluxo de compra da Loja (PaymentService/PaymentProvider)."""

    def __init__(
        self,
        database: Database,
        bot: "LimerenceBot",
        config_service: SubscriptionRenewalConfigService,
        subscription_service: SubscriptionService,
    ) -> None:
        self._database = database
        self._bot = bot
        self._config = config_service
        self._subscriptions = subscription_service

    # --- ciclo de checagem --------------------------------------------------

    async def run_check_cycle(self, guild_id: int, *, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        settings = await self._config.get_settings(guild_id)
        if not settings.enabled:
            return

        async with self._database.session() as session:
            subscriptions = await SubscriptionRepository(session).list_active_with_period(guild_id)
            plans = {
                plan.id: plan for plan in await PlanRepository(session).list_by_guild(guild_id)
            }

        reminder_days = [d for d in await self._config.list_reminder_days(guild_id) if d.enabled]
        smallest = min((d.days_before for d in reminder_days), default=None)

        for subscription in subscriptions:
            plan = plans.get(subscription.plan_id)
            if plan is None:
                continue
            try:
                await self._process_subscription(
                    subscription, plan, settings, reminder_days, smallest, now
                )
            except Exception:
                logger.exception(
                    "Falha ao processar renovação da assinatura %s (guild %s).",
                    subscription.id,
                    guild_id,
                )

    async def _process_subscription(
        self,
        subscription: Subscription,
        plan: Plan,
        settings: SubscriptionRenewalSettings,
        reminder_days: list,
        smallest_days_before: int | None,
        now: datetime,
    ) -> None:
        assert subscription.current_period_end is not None
        period_end = _aware(subscription.current_period_end)
        days_left = days_left_until(period_end, now)

        if period_end > now:
            await self._maybe_send_day_reminders(
                subscription, plan, settings, reminder_days, smallest_days_before, days_left, now
            )
            return

        # --- venceu ---------------------------------------------------------
        if settings.grace_period_days <= 0:
            await self._finish(
                subscription, plan, settings, now, reason=REMINDER_TYPE_EXPIRED
            )
            return

        grace_end = period_end + timedelta(days=settings.grace_period_days)
        if now < grace_end:
            await self._start_grace(subscription, plan, settings, period_end, now)
            if settings.continue_reminders_during_grace:
                await self._maybe_send_day_reminders(
                    subscription,
                    plan,
                    settings,
                    reminder_days,
                    smallest_days_before,
                    days_left_until(grace_end, now),
                    now,
                    period_key=grace_end,
                )
            return

        await self._finish(
            subscription, plan, settings, now, reason=REMINDER_TYPE_GRACE_FINISHED
        )

    async def _maybe_send_day_reminders(
        self,
        subscription: Subscription,
        plan: Plan,
        settings: SubscriptionRenewalSettings,
        reminder_days: list,
        smallest_days_before: int | None,
        days_left: int,
        now: datetime,
        *,
        period_key: datetime | None = None,
    ) -> None:
        period_end = period_key or _aware(subscription.current_period_end)  # type: ignore[arg-type]
        for day in reminder_days:
            if day.days_before != days_left:
                continue
            # o menor "dias antes" configurado é o último aviso — é ele que usa
            # o texto de LAST_REMINDER; todos os outros usam REMINDER
            is_last = smallest_days_before is not None and day.days_before == smallest_days_before
            message_type = (
                SubscriptionMessageType.LAST_REMINDER
                if is_last
                else SubscriptionMessageType.REMINDER
            )
            reminder_type = f"{REMINDER_DAY_PREFIX}{day.days_before}"
            if await self._already_sent(subscription, reminder_type, period_end):
                continue
            delivery = await self._send(
                subscription,
                plan,
                settings,
                message_type,
                days_left=days_left,
                period_end=period_end,
            )
            await self._record_reminder(subscription, reminder_type, period_end, delivery, now)
            await self._audit(
                settings,
                subscription,
                plan,
                action="reminder_sent",
                details={
                    "days_before": day.days_before,
                    "message_type": message_type.value,
                    "delivery": delivery.status,
                },
            )

    async def _start_grace(
        self,
        subscription: Subscription,
        plan: Plan,
        settings: SubscriptionRenewalSettings,
        period_end: datetime,
        now: datetime,
    ) -> None:
        if await self._already_sent(subscription, REMINDER_TYPE_GRACE_STARTED, period_end):
            return
        delivery = await self._send(
            subscription,
            plan,
            settings,
            SubscriptionMessageType.GRACE_PERIOD,
            days_left=0,
            period_end=period_end,
        )
        await self._record_reminder(
            subscription, REMINDER_TYPE_GRACE_STARTED, period_end, delivery, now
        )
        await self._audit(
            settings,
            subscription,
            plan,
            action="grace_started",
            details={"grace_days": settings.grace_period_days, "delivery": delivery.status},
        )

    async def _finish(
        self,
        subscription: Subscription,
        plan: Plan,
        settings: SubscriptionRenewalSettings,
        now: datetime,
        *,
        reason: str,
    ) -> None:
        """Fim de linha: avisa, remove cargo/benefícios e encerra a assinatura,
        respeitando cada toggle de 'Remoção Automática'."""
        period_end = _aware(subscription.current_period_end)  # type: ignore[arg-type]
        if await self._already_sent(subscription, REMINDER_TYPE_EXPIRED, period_end):
            return

        delivery = await self._send(
            subscription,
            plan,
            settings,
            SubscriptionMessageType.EXPIRED,
            days_left=0,
            period_end=period_end,
            allow_dm=settings.send_dm_on_removal,
        )
        await self._record_reminder(
            subscription, REMINDER_TYPE_EXPIRED, period_end, delivery, now
        )

        await self._subscriptions.expire_subscription(
            subscription.id,
            remove_role=settings.remove_roles_on_expire or settings.remove_benefits_on_expire,
            end_subscription=settings.end_subscription_on_expire,
        )

        await self._audit(
            settings, subscription, plan, action=reason, details={"delivery": delivery.status}
        )
        if settings.remove_roles_on_expire or settings.remove_benefits_on_expire:
            await self._audit(
                settings,
                subscription,
                plan,
                action="benefits_removed",
                details={
                    "role_id": plan.role_id,
                    "roles": settings.remove_roles_on_expire,
                    "benefits": settings.remove_benefits_on_expire,
                },
            )

    # --- renovacao concluida -------------------------------------------------

    async def handle_renewed(self, subscription: Subscription, plan: Plan | None = None) -> None:
        """Chamado pelo SubscriptionService quando o período andou pra frente
        (pagamento de renovação aprovado). Idempotente pelo mesmo livro-razão."""
        settings = await self._config.get_settings(subscription.guild_id)
        if not settings.enabled or subscription.current_period_end is None:
            return
        period_end = _aware(subscription.current_period_end)
        if await self._already_sent(subscription, REMINDER_TYPE_RENEWED, period_end):
            return
        if plan is None:
            async with self._database.session() as session:
                plan = await PlanRepository(session).get_by_id(subscription.plan_id)
        if plan is None:
            return
        delivery = await self._send(
            subscription,
            plan,
            settings,
            SubscriptionMessageType.RENEWED,
            days_left=days_left_until(period_end, datetime.now(UTC)),
            period_end=period_end,
        )
        await self._record_reminder(
            subscription, REMINDER_TYPE_RENEWED, period_end, delivery, datetime.now(UTC)
        )
        await self._audit(
            settings,
            subscription,
            plan,
            action="renewed",
            details={"period_end": period_end.isoformat(), "delivery": delivery.status},
        )

    # --- idempotencia / livro-razao -----------------------------------------

    async def _already_sent(
        self, subscription: Subscription, reminder_type: str, period_end: datetime | None
    ) -> bool:
        async with self._database.session() as session:
            return await SubscriptionReminderRepository(session).exists(
                subscription.id, reminder_type, period_end
            )

    async def _record_reminder(
        self,
        subscription: Subscription,
        reminder_type: str,
        period_end: datetime | None,
        delivery: _Delivery,
        now: datetime,
    ) -> None:
        async with self._database.session() as session:
            await SubscriptionReminderRepository(session).add(
                SubscriptionReminder(
                    guild_id=subscription.guild_id,
                    subscription_id=subscription.id,
                    reminder_type=reminder_type,
                    period_end=period_end,
                    sent_at=now,
                    delivery_status=delivery.status,
                )
            )

    async def list_reminders(self, subscription_id) -> list[SubscriptionReminder]:
        async with self._database.session() as session:
            return await SubscriptionReminderRepository(session).list_by_subscription(
                subscription_id
            )

    # --- envio --------------------------------------------------------------

    async def _send(
        self,
        subscription: Subscription,
        plan: Plan,
        settings: SubscriptionRenewalSettings,
        message_type: SubscriptionMessageType,
        *,
        days_left: int,
        period_end: datetime | None,
        allow_dm: bool = True,
    ) -> _Delivery:
        from views.subscription_renewal_buttons import build_renewal_message_view

        guild = self._bot.get_guild(subscription.guild_id)
        if guild is None:
            return _Delivery(DELIVERY_SKIPPED)
        member = guild.get_member(subscription.user_id)
        if member is None:
            try:
                member = await guild.fetch_member(subscription.user_id)
            except discord.HTTPException:
                member = None

        template = await self._config.get_message_content(subscription.guild_id, message_type)
        role = guild.get_role(plan.role_id) if plan.role_id else None
        content = render_placeholders(
            template,
            member=member,
            guild=guild,
            plan=plan,
            role=role,
            renew_date=period_end,
            expires_at=period_end,
            days_left=days_left,
            grace_days=settings.grace_period_days,
            renew_command="/assinatura ver",
            store_command="/loja",
            subscription_id=subscription.id,
        )
        buttons = await self._config.list_buttons(subscription.guild_id)
        view = build_renewal_message_view(
            guild_id=subscription.guild_id,
            subscription_id=subscription.id,
            plan_id=plan.id,
            buttons=buttons,
        )

        attempted = False
        delivered = False

        if allow_dm and settings.notify_via_dm and member is not None:
            attempted = True
            try:
                if view is not None:
                    await member.send(content, view=view)
                else:
                    await member.send(content)
                delivered = True
            except discord.Forbidden:
                logger.info("DM bloqueada para %s (guild %s).", subscription.user_id, guild.id)
            except discord.HTTPException:
                logger.exception("Falha ao enviar DM de renovação para %s.", subscription.user_id)

        if settings.notify_via_channel and settings.renewal_channel_id is not None:
            channel = guild.get_channel(settings.renewal_channel_id)
            if isinstance(channel, discord.abc.Messageable):
                attempted = True
                mention = member.mention if member is not None else f"<@{subscription.user_id}>"
                body = content if member is not None else f"{mention}\n{content}"
                try:
                    if view is not None:
                        await channel.send(body, view=view)
                    else:
                        await channel.send(body)
                    delivered = True
                except discord.HTTPException:
                    logger.exception(
                        "Falha ao enviar aviso de renovação no canal da guild %s.", guild.id
                    )

        if not attempted:
            return _Delivery(DELIVERY_SKIPPED)
        return _Delivery(DELIVERY_SENT if delivered else DELIVERY_FAILED)

    # --- auditoria -----------------------------------------------------------

    async def _audit(
        self,
        settings: SubscriptionRenewalSettings,
        subscription: Subscription,
        plan: Plan,
        *,
        action: str,
        details: dict[str, object] | None = None,
    ) -> None:
        if not settings.log_audit:
            return
        payload: dict[str, object] = {
            "plan": plan.name,
            "subscription_id": str(subscription.id),
        }
        payload.update(details or {})
        await self._bot.audit_log_service.record(
            guild_id=subscription.guild_id,
            category=AuditLogCategory.SUBSCRIPTION,
            action=action,
            executor_name="Sistema de Renovação",
            target_id=subscription.user_id,
            details=payload,
        )
