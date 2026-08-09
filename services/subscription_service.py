from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import discord

from core.logger import get_logger
from database.database import Database
from database.models.audit_log import AuditLogCategory
from database.models.monetization_settings import MonetizationSettings
from database.models.payment import PaymentHistory, PaymentStatus
from database.models.plan import Plan
from database.models.plan_message import PlanMessageType
from database.models.subscription import BillingCycle, Subscription, SubscriptionStatus
from database.models.subscription_history import SubscriptionEventType, SubscriptionHistory
from database.repositories.monetization_settings_repository import MonetizationSettingsRepository
from database.repositories.payment_dm_settings_repository import PaymentDmSettingsRepository
from database.repositories.plan_repository import PlanMessageRepository, PlanRepository
from database.repositories.player_repository import PlayerRepository
from database.repositories.subscription_history_repository import SubscriptionHistoryRepository
from database.repositories.subscription_repository import SubscriptionRepository
from providers.base import ChargeRequest, ChargeResult
from services.payment_service import PaymentService
from services.plan_service import render_placeholders

if TYPE_CHECKING:
    from core.bot import LimerenceBot

logger = get_logger("subscription_service")

_DEFAULT_MESSAGES: dict[PlanMessageType, str] = {
    PlanMessageType.PURCHASE: "🎉 Obrigado por assinar **{plan_name}** em {server_name}!",
    PlanMessageType.RENEWAL: "🔄 Sua assinatura de **{plan_name}** foi renovada até {renew_date}.",
    PlanMessageType.CANCELLATION: "😢 Sua assinatura de **{plan_name}** em {server_name} foi cancelada.",
    PlanMessageType.THANK_YOU: "💜 Obrigado pelo seu apoio a {server_name}!",
    PlanMessageType.UPGRADE: "⬆️ Você fez upgrade para **{plan_name}**!",
    PlanMessageType.DOWNGRADE: "⬇️ Seu plano foi alterado para **{plan_name}**.",
}

_CYCLE_LENGTH: dict[BillingCycle, timedelta | None] = {
    BillingCycle.MONTHLY: timedelta(days=30),
    BillingCycle.YEARLY: timedelta(days=365),
    BillingCycle.ONE_TIME: None,
}


class DuplicateSubscriptionError(ValueError):
    pass


class MissingPriceError(ValueError):
    pass


def _price_for_cycle(plan: Plan, cycle: BillingCycle) -> int | None:
    return {
        BillingCycle.MONTHLY: plan.price_monthly,
        BillingCycle.YEARLY: plan.price_yearly,
        BillingCycle.ONE_TIME: plan.price_one_time,
    }[cycle]


class SubscriptionService:
    """Orquestra o fluxo de compra/confirmacao/cancelamento/renovacao das
    assinaturas de Planos. Toda entrega de cargo, DM e log passa por aqui —
    Cogs/Views nunca falam direto com repositorios/provider."""

    def __init__(self, database: Database, bot: LimerenceBot, payment_service: PaymentService) -> None:
        self._database = database
        self._bot = bot
        self._payments = payment_service

    # --- configuracao -------------------------------------------------------

    async def get_settings(self, guild_id: int) -> MonetizationSettings:
        async with self._database.session() as session:
            return await MonetizationSettingsRepository(session).get_or_create(guild_id)

    async def update_settings(self, guild_id: int, **fields: object) -> MonetizationSettings:
        async with self._database.session() as session:
            repo = MonetizationSettingsRepository(session)
            settings = await repo.get_or_create(guild_id)
            for key, value in fields.items():
                setattr(settings, key, value)
            await session.flush()
            await session.refresh(settings)
            return settings

    # --- compra ---------------------------------------------------------

    async def start_purchase(
        self,
        member: discord.Member,
        plan: Plan,
        billing_cycle: BillingCycle,
        *,
        renewal: bool = False,
        coupon_code: str | None = None,
        payer_information: str | None = None,
    ) -> tuple[Subscription, PaymentHistory, ChargeResult]:
        """`renewal=True` (botão "Renovar" das mensagens de renovação) permite
        cobrar uma assinatura ATIVA que já passou do vencimento (está em
        carência). Nesse caso a linha NÃO volta pra PENDING nem perde
        current_period_end: se o pagamento não for concluído, a carência segue
        correndo normalmente e expira como qualquer outra. O caminho de
        cobrança em si é exatamente o mesmo da Loja."""
        amount = _price_for_cycle(plan, billing_cycle)
        if amount is None:
            raise MissingPriceError("Este plano não tem preço configurado para esse ciclo de cobrança.")

        # `coupon_code` e opcional e puramente aditivo: sem ele o fluxo e
        # identico ao de sempre. Com ele, o cupom e validado e o desconto
        # calculado ANTES de qualquer ChargeRequest — nunca se gera cobranca
        # antes da validacao passar. Toda a regra (limites/janela/plano/ciclo/
        # cargo obrigatorio) e toda a matematica vivem no CouponService.
        coupon_application = None
        if coupon_code:
            coupon_application = await self._bot.coupon_service.validate_and_price(
                member.guild.id, coupon_code, member, plan, billing_cycle, amount
            )
            amount = coupon_application.final_amount

        provider = await self._payments.resolve_provider(member.guild.id)
        gateway_settings = await self._payments.get_gateway_settings(member.guild.id)

        async with self._database.session() as session:
            sub_repo = SubscriptionRepository(session)
            active_or_pending = await sub_repo.get_active_for_user_plan(member.guild.id, member.id, plan.id)
            renewing_row = (
                active_or_pending
                if renewal
                and active_or_pending is not None
                and active_or_pending.status == SubscriptionStatus.ACTIVE
                and active_or_pending.current_period_end is not None
                and active_or_pending.current_period_end <= datetime.now(UTC)
                else None
            )
            if active_or_pending is not None and renewing_row is None:
                raise DuplicateSubscriptionError(
                    "Você já possui uma assinatura ativa ou pendente para este plano."
                )
            external_reference = f"{member.guild.id}:{member.id}:{plan.id}:{uuid.uuid4()}"

            if renewing_row is not None:
                renewing_row.billing_cycle = billing_cycle
                renewing_row.provider = provider.name
                renewing_row.external_reference = external_reference
                await session.flush()
                subscription = renewing_row
            else:
                # linha e unica por guild+user+plan (historico nunca some) — recompra
                # reaproveita a mesma linha em vez de tentar inserir outra
                existing_row = await sub_repo.get_by_user_plan(member.guild.id, member.id, plan.id)
                if existing_row is not None:
                    existing_row.status = SubscriptionStatus.PENDING
                    existing_row.billing_cycle = billing_cycle
                    existing_row.provider = provider.name
                    existing_row.external_reference = external_reference
                    existing_row.started_at = None
                    existing_row.current_period_end = None
                    existing_row.canceled_at = None
                    await session.flush()
                    subscription = existing_row
                else:
                    subscription = await sub_repo.add(
                        Subscription(
                            guild_id=member.guild.id,
                            user_id=member.id,
                            plan_id=plan.id,
                            status=SubscriptionStatus.PENDING,
                            billing_cycle=billing_cycle,
                            provider=provider.name,
                            external_reference=external_reference,
                        )
                    )

        request = ChargeRequest(
            guild_id=member.guild.id,
            user_id=member.id,
            plan_id=str(plan.id),
            plan_name=plan.name,
            amount=amount,
            currency=plan.currency,
            billing_cycle=billing_cycle,
            external_reference=external_reference,
            expires_in_minutes=gateway_settings.pix_expiration_minutes,
        )
        result, payment = await self._payments.charge(request, provider, payer_information=payer_information)
        await self._payments.link_subscription(payment.id, subscription.id)
        if coupon_application is not None:
            await self._bot.coupon_service.record_redemption(
                coupon_application.coupon.id,
                member.guild.id,
                member.id,
                payment.id,
                coupon_application.original_amount,
                coupon_application.discount_amount,
                coupon_application.final_amount,
            )
        await self._audit(
            subscription, plan, action="Cobrança criada",
            executor_id=member.id, executor_name=str(member),
        )
        return subscription, payment, result

    # --- confirmacao (aprovacao manual ou webhook de um gateway futuro) -----

    async def confirm_payment(
        self,
        payment_id: uuid.UUID,
        *,
        executor: discord.Member | discord.User | None = None,
    ) -> Subscription | None:
        payment = await self._payments.get(payment_id)
        if payment is None or payment.subscription_id is None:
            return None
        if payment.status == PaymentStatus.APPROVED:
            # ja processado — idempotente, evita cargo/DM duplicados em reprocessamento
            async with self._database.session() as session:
                return await SubscriptionRepository(session).get_by_id(payment.subscription_id)
        if payment.status != PaymentStatus.PENDING:
            # rejeitado/cancelado/expirado antes — nao pode aprovar depois disso,
            # senao um clique tardio em "Aprovar" entregaria cargo/beneficio pra
            # um pedido que a staff (ou o proprio comprador) ja encerrou
            return None

        now = datetime.now(UTC)
        updated = await self._payments.set_status(
            payment.id, PaymentStatus.APPROVED, paid_at=now,
            expected_statuses=(PaymentStatus.PENDING,),
        )
        if updated is None:
            # outra transacao concorrente (webhook + clique manual, ou dois
            # cliques de staff) ja mudou o status entre a leitura acima e
            # aqui — perdeu a corrida, nao entrega beneficio duplicado
            return None

        async with self._database.session() as session:
            sub_repo = SubscriptionRepository(session)
            subscription = await sub_repo.get_by_id(payment.subscription_id)
            if subscription is None:
                return None
            cycle_length = _CYCLE_LENGTH[subscription.billing_cycle]
            # se ja existia um periodo, esta aprovacao e uma RENOVACAO (botao
            # "Renovar" ou recompra), nao uma assinatura nova
            was_renewal = subscription.started_at is not None
            subscription.status = SubscriptionStatus.ACTIVE
            subscription.started_at = now
            subscription.current_period_end = now + cycle_length if cycle_length else None
            await session.flush()
            await session.refresh(subscription)

            plan = await PlanRepository(session).get_by_id(subscription.plan_id)
            await SubscriptionHistoryRepository(session).add(
                SubscriptionHistory(
                    subscription_id=subscription.id,
                    event_type=SubscriptionEventType.CREATED,
                    to_plan_id=subscription.plan_id,
                )
            )

        if plan is not None:
            if plan.product_id is None:
                # sem Product vinculado: caminho legado, bot entrega o cargo
                # direto (nao ha License pra gerar evento)
                await self._deliver_role(subscription, plan)
            else:
                # com Product vinculado: bot NAO e mais fonte de verdade do
                # beneficio — _grant_license concede a License, que publica
                # evento no EventBus, e RoleSyncService (reagindo ao evento)
                # e quem entrega o cargo. Entregar aqui tambem duplicaria a
                # causalidade que a Fase 5 pede pra quebrar.
                await self._grant_license(subscription, plan, payment)
            await self._send_plan_message(subscription, plan, PlanMessageType.PURCHASE)
            try:
                await self._send_payment_dm(subscription, plan, payment, approved=True, executor=executor)
            except Exception:
                logger.exception("Falha ao enviar DM de aprovacao do pagamento %s.", payment.id)
            await self._log(subscription, plan, "✅ Assinatura confirmada.")
            await self._audit(
                subscription, plan, action="Pagamento aprovado",
                executor_id=executor.id if executor else None,
                executor_name=str(executor) if executor else None,
            )
            if was_renewal:
                await self._notify_renewed(subscription, plan)
        return subscription

    async def reject_payment(
        self,
        payment_id: uuid.UUID,
        *,
        reason: str | None = None,
        executor: discord.Member | discord.User | None = None,
    ) -> bool:
        payment = await self._payments.get(payment_id)
        if payment is None or payment.status != PaymentStatus.PENDING:
            return False  # idempotente — so processa pagamento ainda pendente
        updated = await self._payments.set_status(
            payment.id, PaymentStatus.REJECTED,
            expected_statuses=(PaymentStatus.PENDING,),
        )
        if updated is None:
            return False  # perdeu a corrida — outra transacao ja mudou o status
        if payment.subscription_id is None:
            return True
        async with self._database.session() as session:
            sub_repo = SubscriptionRepository(session)
            subscription = await sub_repo.get_by_id(payment.subscription_id)
            if subscription is None:
                return True
            plan = await PlanRepository(session).get_by_id(subscription.plan_id)
            # renovacao em carencia: a linha segue ATIVA e o periodo atual nao
            # muda — so registramos a falha, quem expira e o scheduler
            renewal_in_flight = subscription.status == SubscriptionStatus.ACTIVE
            if not renewal_in_flight:
                if subscription.status != SubscriptionStatus.PENDING:
                    return True
                subscription.status = SubscriptionStatus.CANCELED
                subscription.canceled_at = datetime.now(UTC)
                await session.flush()

        if plan is not None:
            try:
                await self._send_payment_dm(subscription, plan, payment, approved=False, executor=executor)
            except Exception:
                logger.exception("Falha ao enviar DM de rejeicao do pagamento %s.", payment.id)
            await self._log(subscription, plan, f"❌ Pagamento rejeitado. {reason or ''}".strip())
            await self._audit(
                subscription, plan, action="Pagamento rejeitado", reason=reason,
                executor_id=executor.id if executor else None,
                executor_name=str(executor) if executor else None,
            )
            if renewal_in_flight:
                await self._audit_subscription(
                    subscription, plan, action="renewal_failed",
                    reason=reason or "Pagamento rejeitado",
                    executor_id=executor.id if executor else None,
                    executor_name=str(executor) if executor else None,
                )
        return True

    async def mark_payment_pending(
        self,
        payment_id: uuid.UUID,
        *,
        executor: discord.Member | discord.User | None = None,
    ) -> PaymentHistory | None:
        """Botao "Marcar como Pendente" do painel de aprovacao — reverte um
        pagamento que estava sendo processado/rejeitado de volta pra fila de
        analise, sem mexer no cargo/assinatura (idempotente: so age sobre
        pagamento que ainda nao foi aprovado nem cancelado/expirado)."""
        payment = await self._payments.get(payment_id)
        if payment is None or payment.status not in (PaymentStatus.PROCESSING, PaymentStatus.REJECTED):
            return None
        payment = await self._payments.set_status(
            payment.id, PaymentStatus.PENDING,
            expected_statuses=(PaymentStatus.PROCESSING, PaymentStatus.REJECTED),
        )
        if payment is None or payment.subscription_id is None:
            return payment
        async with self._database.session() as session:
            subscription = await SubscriptionRepository(session).get_by_id(payment.subscription_id)
            if subscription is None:
                return payment
            plan = await PlanRepository(session).get_by_id(subscription.plan_id)
        if plan is not None:
            await self._log(subscription, plan, "⏳ Pagamento marcado como pendente novamente.")
            await self._audit(
                subscription, plan, action="Pagamento marcado como pendente",
                executor_id=executor.id if executor else None,
                executor_name=str(executor) if executor else None,
            )
        return payment

    async def cancel_payment(
        self,
        payment_id: uuid.UUID,
        *,
        executor: discord.Member | discord.User | None = None,
    ) -> bool:
        """Botao "Cancelar Pedido" do painel de aprovacao — encerra a cobranca
        (status CANCELED, distinto de EXPIRED que so o scheduler usa) e, se o
        pedido nunca chegou a ser aprovado, cancela a assinatura pendente
        junto. Idempotente: so age sobre pagamento ainda em aberto. Retorna
        False sem alterar nada se o pagamento ja tiver sido processado
        (aprovado/rejeitado/expirado/cancelado antes)."""
        payment = await self._payments.get(payment_id)
        if payment is None or payment.status not in (PaymentStatus.PENDING, PaymentStatus.PROCESSING):
            return False
        updated = await self._payments.set_status(
            payment.id, PaymentStatus.CANCELED,
            expected_statuses=(PaymentStatus.PENDING, PaymentStatus.PROCESSING),
        )
        if updated is None:
            return False  # perdeu a corrida — outra transacao ja mudou o status
        if payment.subscription_id is None:
            return True
        async with self._database.session() as session:
            sub_repo = SubscriptionRepository(session)
            subscription = await sub_repo.get_by_id(payment.subscription_id)
            if subscription is None:
                return True
            plan = await PlanRepository(session).get_by_id(subscription.plan_id)
            renewal_in_flight = subscription.status == SubscriptionStatus.ACTIVE
            if not renewal_in_flight:
                if subscription.status != SubscriptionStatus.PENDING:
                    return True
                subscription.status = SubscriptionStatus.CANCELED
                subscription.canceled_at = datetime.now(UTC)
                await session.flush()

        if plan is not None:
            await self._log(subscription, plan, "🚫 Pedido cancelado pela equipe.")
            await self._audit(
                subscription, plan, action="Pedido cancelado pela equipe",
                executor_id=executor.id if executor else None,
                executor_name=str(executor) if executor else None,
            )
        return True

    # --- cancelamento ---------------------------------------------------

    async def cancel_subscription(
        self,
        subscription_id: uuid.UUID,
        *,
        remove_role: bool = True,
        executor: discord.Member | discord.User | None = None,
    ) -> Subscription | None:
        async with self._database.session() as session:
            sub_repo = SubscriptionRepository(session)
            subscription = await sub_repo.get_by_id(subscription_id)
            if subscription is None or subscription.status not in (
                SubscriptionStatus.ACTIVE, SubscriptionStatus.PENDING,
            ):
                return subscription
            was_active = subscription.status == SubscriptionStatus.ACTIVE
            plan = await PlanRepository(session).get_by_id(subscription.plan_id)
            subscription.status = SubscriptionStatus.CANCELED
            subscription.canceled_at = datetime.now(UTC)
            await session.flush()
            await session.refresh(subscription)
            await SubscriptionHistoryRepository(session).add(
                SubscriptionHistory(
                    subscription_id=subscription.id,
                    event_type=SubscriptionEventType.CANCELED,
                    from_plan_id=subscription.plan_id,
                )
            )

        if plan is None:
            return subscription

        executor_id = executor.id if executor else None
        executor_name = str(executor) if executor else None

        if not was_active:
            # pendente nunca chegou a entregar cargo/DM de boas-vindas — so cancela
            await self._audit(
                subscription, plan, action="Assinatura cancelada (ainda pendente)",
                executor_id=executor_id, executor_name=executor_name,
            )
            return subscription

        # recompensas permanentes (pagamento unico) nunca sao removidas no cancelamento
        if subscription.billing_cycle != BillingCycle.ONE_TIME:
            if plan.product_id is None:
                if remove_role:
                    await self._remove_role(subscription, plan)
            else:
                await self._revoke_license(subscription, plan, reason="Assinatura cancelada")

        await self._send_plan_message(subscription, plan, PlanMessageType.CANCELLATION)
        await self._log(subscription, plan, "🚫 Assinatura cancelada.")
        await self._audit(
            subscription, plan, action="Assinatura cancelada",
            executor_id=executor_id, executor_name=executor_name,
        )
        await self._audit_subscription(
            subscription, plan, action="renewal_canceled",
            executor_id=executor_id, executor_name=executor_name,
        )
        return subscription

    # --- renovacao (chamada quando o gateway confirmar uma cobranca recorrente) ---

    async def renew_subscription(self, subscription_id: uuid.UUID) -> Subscription | None:
        async with self._database.session() as session:
            sub_repo = SubscriptionRepository(session)
            subscription = await sub_repo.get_by_id(subscription_id)
            if subscription is None or subscription.status != SubscriptionStatus.ACTIVE:
                return subscription
            cycle_length = _CYCLE_LENGTH[subscription.billing_cycle]
            if cycle_length is None:
                return subscription  # pagamento unico nao renova
            base = subscription.current_period_end or datetime.now(UTC)
            subscription.current_period_end = base + cycle_length
            await session.flush()
            await session.refresh(subscription)
            plan = await PlanRepository(session).get_by_id(subscription.plan_id)
            await SubscriptionHistoryRepository(session).add(
                SubscriptionHistory(
                    subscription_id=subscription.id,
                    event_type=SubscriptionEventType.RENEWED,
                    to_plan_id=subscription.plan_id,
                )
            )

        if plan is not None:
            await self._send_plan_message(subscription, plan, PlanMessageType.RENEWAL)
            await self._log(subscription, plan, "🔄 Assinatura renovada.")
            await self._audit(subscription, plan, action="Assinatura renovada")
            await self._notify_renewed(subscription, plan)
        return subscription

    # --- expiracao de assinatura (fim do periodo/carencia) ------------------

    async def expire_subscription(
        self, subscription_id: uuid.UUID, *, remove_role: bool = True, end_subscription: bool = True
    ) -> Subscription | None:
        """Encerra uma assinatura vencida: remove o cargo do plano (mesmo
        mecanismo do cancelamento) e marca EXPIRED. Não envia mensagem — quem
        avisa o usuário é o SubscriptionReminderService, com o texto que a
        guild configurou. Idempotente: só age sobre assinatura ATIVA."""
        async with self._database.session() as session:
            sub_repo = SubscriptionRepository(session)
            subscription = await sub_repo.get_by_id(subscription_id)
            if subscription is None or subscription.status != SubscriptionStatus.ACTIVE:
                return subscription
            plan = await PlanRepository(session).get_by_id(subscription.plan_id)
            if end_subscription:
                subscription.status = SubscriptionStatus.EXPIRED
                await session.flush()
                await session.refresh(subscription)
                await SubscriptionHistoryRepository(session).add(
                    SubscriptionHistory(
                        subscription_id=subscription.id,
                        event_type=SubscriptionEventType.EXPIRED,
                        from_plan_id=subscription.plan_id,
                    )
                )

        if plan is None:
            return subscription
        # recompensa permanente (pagamento unico) nunca e removida
        if subscription.billing_cycle != BillingCycle.ONE_TIME:
            if plan.product_id is None:
                if remove_role:
                    await self._remove_role(subscription, plan)
            else:
                await self._revoke_license(subscription, plan, reason="Assinatura expirada")
        await self._log(subscription, plan, "⌛ Assinatura expirada.")
        return subscription

    async def get_subscription(self, subscription_id: uuid.UUID) -> Subscription | None:
        async with self._database.session() as session:
            return await SubscriptionRepository(session).get_by_id(subscription_id)

    # --- expiracao (loop de PIX vencido) --------------------------------

    async def expire_payment(self, payment_id: uuid.UUID) -> bool:
        """Retorna True somente se a cobrança realmente foi expirada agora —
        mesmo padrão de reject_payment/cancel_payment: idempotente (retorna
        False sem alterar nada se o pagamento já não estiver mais PENDING),
        pra chamadores (ex.: botão "Cancelar cobrança" do comprador) não
        reportarem sucesso quando nada mudou (ex.: staff aprovou o pagamento
        entre a checagem do botão e esta chamada)."""
        payment = await self._payments.get(payment_id)
        if payment is None or payment.status != PaymentStatus.PENDING:
            return False  # idempotente — so expira pagamento ainda pendente
        updated = await self._payments.set_status(
            payment.id, PaymentStatus.EXPIRED,
            expected_statuses=(PaymentStatus.PENDING,),
        )
        if updated is None:
            return False  # perdeu a corrida — outra transacao ja mudou o status
        if payment.subscription_id is None:
            return True
        async with self._database.session() as session:
            sub_repo = SubscriptionRepository(session)
            subscription = await sub_repo.get_by_id(payment.subscription_id)
            if subscription is None:
                return True
            plan = await PlanRepository(session).get_by_id(subscription.plan_id)
            # mesma logica de reject_payment: renovacao em carencia nao cancela
            # a assinatura, so registra a falha da cobranca
            renewal_in_flight = subscription.status == SubscriptionStatus.ACTIVE
            if not renewal_in_flight:
                if subscription.status != SubscriptionStatus.PENDING:
                    return True
                subscription.status = SubscriptionStatus.CANCELED
                subscription.canceled_at = datetime.now(UTC)
                await session.flush()

        if plan is not None:
            await self._log(subscription, plan, "⌛ Cobrança PIX expirou sem pagamento.")
            await self._audit(subscription, plan, action="Pagamento expirado")
            if renewal_in_flight:
                await self._audit_subscription(
                    subscription, plan, action="renewal_failed",
                    reason="Cobrança de renovação expirou sem pagamento",
                )
        return True

    # --- reembolso/chargeback (webhook) ----------------------------------

    async def handle_refund_or_chargeback(self, payment_id: uuid.UUID, *, chargeback: bool = False) -> None:
        payment = await self._payments.get(payment_id)
        if payment is None or payment.subscription_id is None:
            return
        async with self._database.session() as session:
            sub_repo = SubscriptionRepository(session)
            subscription = await sub_repo.get_by_id(payment.subscription_id)
            if subscription is None or subscription.status != SubscriptionStatus.ACTIVE:
                return
            plan = await PlanRepository(session).get_by_id(subscription.plan_id)
            subscription.status = SubscriptionStatus.CANCELED
            subscription.canceled_at = datetime.now(UTC)
            await session.flush()
            await session.refresh(subscription)
            await SubscriptionHistoryRepository(session).add(
                SubscriptionHistory(
                    subscription_id=subscription.id,
                    event_type=SubscriptionEventType.CANCELED,
                    from_plan_id=subscription.plan_id,
                    note="chargeback" if chargeback else "refund",
                )
            )

        if plan is None:
            return

        label = "Chargeback recebido" if chargeback else "Reembolso realizado"
        if plan.product_id is None:
            await self._remove_role(subscription, plan)
        else:
            await self._revoke_license(subscription, plan, reason=label)
        await self._send_plan_message(subscription, plan, PlanMessageType.CANCELLATION)
        await self._log(subscription, plan, f"⚠️ {label} — assinatura cancelada e cargo removido.")
        await self._audit(subscription, plan, action=label)

    # --- consulta (base pra API/integracao com jogos) -----------------------

    async def list_active_subscriptions(self, guild_id: int, user_id: int) -> list[Subscription]:
        async with self._database.session() as session:
            return await SubscriptionRepository(session).list_active_by_user(guild_id, user_id)

    async def list_guild_subscriptions(self, guild_id: int) -> list[Subscription]:
        """Todas as assinaturas da guild — base do painel administrativo de
        renovação (histórico incluso)."""
        async with self._database.session() as session:
            return await SubscriptionRepository(session).list_by_guild(guild_id)

    async def list_cancelable_subscriptions(self, guild_id: int, user_id: int) -> list[Subscription]:
        """Ativas + pendentes — usado por /assinatura cancelar (staff), que
        precisa conseguir limpar uma assinatura travada em PENDING mesmo sem
        pagamento aprovado, senao o usuario fica preso e nao consegue comprar
        de novo (uq_subscription_guild_user_plan bloqueia)."""
        async with self._database.session() as session:
            return await SubscriptionRepository(session).list_active_or_pending_by_user(guild_id, user_id)

    # --- entrega/remocao de cargo, mensagens e log --------------------------

    async def _get_member(self, subscription: Subscription) -> discord.Member | None:
        guild = self._bot.get_guild(subscription.guild_id)
        if guild is None:
            return None
        member = guild.get_member(subscription.user_id)
        if member is not None:
            return member
        try:
            return await guild.fetch_member(subscription.user_id)
        except discord.HTTPException:
            return None

    async def _deliver_role(self, subscription: Subscription, plan: Plan) -> None:
        if plan.role_id is None:
            return
        member = await self._get_member(subscription)
        if member is None:
            return
        role = member.guild.get_role(plan.role_id)
        if role is None or role in member.roles:
            return
        try:
            await member.add_roles(role, reason=f"Monetização: assinatura do plano {plan.name}")
        except discord.Forbidden:
            logger.warning("Sem permissão para entregar cargo do plano %s na guild %s.", plan.id, subscription.guild_id)
        except discord.HTTPException:
            logger.exception("Falha ao entregar cargo do plano %s na guild %s.", plan.id, subscription.guild_id)

    async def _remove_role(self, subscription: Subscription, plan: Plan) -> None:
        if plan.role_id is None:
            return
        member = await self._get_member(subscription)
        if member is None:
            return
        role = member.guild.get_role(plan.role_id)
        if role is None or role not in member.roles:
            return
        try:
            await member.remove_roles(role, reason=f"Monetização: assinatura do plano {plan.name} cancelada")
        except discord.Forbidden:
            logger.warning("Sem permissão para remover cargo do plano %s na guild %s.", plan.id, subscription.guild_id)
        except discord.HTTPException:
            logger.exception("Falha ao remover cargo do plano %s na guild %s.", plan.id, subscription.guild_id)

    async def _send_plan_message(
        self, subscription: Subscription, plan: Plan, message_type: PlanMessageType
    ) -> None:
        member = await self._get_member(subscription)
        if member is None:
            return
        async with self._database.session() as session:
            record = await PlanMessageRepository(session).get_by_plan_and_type(plan.id, message_type)
        template = record.content if record is not None else _DEFAULT_MESSAGES[message_type]
        role = member.guild.get_role(plan.role_id) if plan.role_id else None
        content = render_placeholders(
            template,
            member=member,
            guild=member.guild,
            plan=plan,
            role=role,
            renew_date=subscription.current_period_end,
        )
        try:
            await member.send(content)
        except discord.Forbidden:
            pass
        except discord.HTTPException:
            logger.exception("Falha ao enviar DM de monetização para %s.", member.id)

    async def _send_payment_dm(
        self,
        subscription: Subscription,
        plan: Plan,
        payment: PaymentHistory,
        *,
        approved: bool,
        executor: discord.Member | discord.User | None = None,
    ) -> None:
        """DM dedicada de aprovacao/rejeicao (distinta da mensagem generica de
        compra) — totalmente configuravel por /config painel -> Monetizacao ->
        Mensagens ao Comprador. Nunca bloqueia a aprovacao/rejeicao: falha de
        DM (bloqueada, servidor nao compartilha DM, erro da API) so vira um
        registro na auditoria, igual ao padrao de cogs/moderation.py."""
        member = await self._get_member(subscription)
        if member is None:
            return
        async with self._database.session() as session:
            settings = await PaymentDmSettingsRepository(session).get_or_create(subscription.guild_id)
        if not (settings.approved_enabled if approved else settings.rejected_enabled):
            return

        from views.embeds import payment_dm_embed

        embed = payment_dm_embed(
            settings, approved=approved, member=member, plan=plan, payment=payment, staff=executor
        )
        dm_sent = False
        try:
            await member.send(embed=embed)
            dm_sent = True
        except discord.Forbidden:
            pass
        except discord.HTTPException:
            logger.exception(
                "Falha ao enviar DM de %s para %s.", "aprovação" if approved else "rejeição", member.id
            )

        await self._bot.audit_log_service.record(
            guild_id=subscription.guild_id,
            category=AuditLogCategory.PAYMENT,
            action="DM ao comprador enviada" if dm_sent else "Falha ao enviar DM ao comprador",
            executor_id=executor.id if executor else None,
            executor_name=str(executor) if executor else None,
            target_id=subscription.user_id,
            details={"dm_sent": dm_sent, "approved": approved, "payment_id": str(payment.id)},
        )

    async def _audit(
        self,
        subscription: Subscription,
        plan: Plan,
        *,
        action: str,
        executor_id: int | None = None,
        executor_name: str | None = None,
        reason: str | None = None,
    ) -> None:
        await self._bot.audit_log_service.record(
            guild_id=subscription.guild_id,
            category=AuditLogCategory.PAYMENT,
            action=action,
            executor_id=executor_id,
            executor_name=executor_name,
            target_id=subscription.user_id,
            reason=reason,
            details={"plan": plan.name, "billing_cycle": subscription.billing_cycle.value},
        )

    async def _audit_subscription(
        self,
        subscription: Subscription,
        plan: Plan,
        *,
        action: str,
        reason: str | None = None,
        executor_id: int | None = None,
        executor_name: str | None = None,
    ) -> None:
        """Auditoria na categoria SUBSCRIPTION (ciclo de vida/renovação), em
        paralelo à categoria PAYMENT (cobrança)."""
        await self._bot.audit_log_service.record(
            guild_id=subscription.guild_id,
            category=AuditLogCategory.SUBSCRIPTION,
            action=action,
            executor_id=executor_id,
            executor_name=executor_name,
            target_id=subscription.user_id,
            reason=reason,
            details={"plan": plan.name, "subscription_id": str(subscription.id)},
        )

    async def _grant_license(self, subscription: Subscription, plan: Plan, payment: PaymentHistory) -> None:
        """Concede/renova a License do Product vinculado ao plano (se algum).
        Acoplamento opcional de proposito, mesmo padrao de _notify_renewed: se
        license_service nao estiver montado (ex.: testes) ou o plano nao tiver
        product_id, o fluxo de pagamento continua funcionando igual — License
        e um beneficio adicional sobre o cargo Discord, nunca um requisito
        pra aprovar o pagamento."""
        if plan.product_id is None:
            return
        license_service = getattr(self._bot, "license_service", None)
        if license_service is None:
            return
        try:
            async with self._database.session() as session:
                player = await PlayerRepository(session).get_or_create_by_discord_id(
                    subscription.user_id, discord_username=None, linked_at=datetime.now(UTC)
                )
            await license_service.grant_or_renew(
                player.id,
                plan.product_id,
                purchase_source=f"subscription:{plan.name}",
                external_reference=str(payment.id),
                expires_at=subscription.current_period_end,
                auto_renew=subscription.billing_cycle != BillingCycle.ONE_TIME,
            )
        except Exception:
            logger.exception("Falha ao conceder licenca da assinatura %s.", subscription.id)

    async def _revoke_license(self, subscription: Subscription, plan: Plan, *, reason: str) -> None:
        """Revoga a License do Product vinculado ao plano (se algum) — mesmo
        acoplamento opcional de _grant_license. So age se o Player ja existir
        (sem player nunca houve License pra revogar)."""
        if plan.product_id is None:
            return
        license_service = getattr(self._bot, "license_service", None)
        if license_service is None:
            return
        try:
            async with self._database.session() as session:
                player = await PlayerRepository(session).get_by_discord_id(subscription.user_id)
            if player is None:
                return
            await license_service.revoke_by_player_product(player.id, plan.product_id, reason=reason)
        except Exception:
            logger.exception("Falha ao revogar licenca da assinatura %s.", subscription.id)

    async def _notify_renewed(self, subscription: Subscription, plan: Plan) -> None:
        """Avisa o serviço de renovação que o período andou pra frente. Acoplamento
        opcional de propósito: se o serviço não estiver montado (ex.: testes), o
        fluxo de pagamento continua funcionando igual."""
        reminder_service = getattr(self._bot, "subscription_reminder_service", None)
        if reminder_service is None:
            return
        try:
            await reminder_service.handle_renewed(subscription, plan)
        except Exception:
            logger.exception(
                "Falha ao notificar renovação da assinatura %s.", subscription.id
            )

    async def _log(self, subscription: Subscription, plan: Plan, message: str) -> None:
        settings = await self.get_settings(subscription.guild_id)
        if settings.log_channel_id is None:
            return
        guild = self._bot.get_guild(subscription.guild_id)
        if guild is None:
            return
        channel = guild.get_channel(settings.log_channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            return
        from utils.constants import EMBED_COLOR_PURPLE

        embed = discord.Embed(
            title="💰 Monetização",
            description=message,
            color=EMBED_COLOR_PURPLE,
        )
        embed.add_field(name="Plano", value=plan.name)
        embed.add_field(name="Usuário", value=f"<@{subscription.user_id}>")
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            logger.exception("Falha ao enviar log de monetização na guild %s.", subscription.guild_id)
