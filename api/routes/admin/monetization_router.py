from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import discord
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, or_, select

from api.routes.admin.security import require_local_admin
from api.schemas.admin import (
    MonetizationAlert,
    MonetizationCouponRow,
    MonetizationMetric,
    MonetizationPlanRow,
    MonetizationRecentPayment,
    MonetizationStatusBreakdown,
    MonetizationSummaryResponse,
)
from database.models.discount_coupon import DiscountCoupon, DiscountType
from database.models.monetization_settings import MonetizationSettings
from database.models.payment import PaymentHistory, PaymentStatus
from database.models.plan import Plan
from database.models.product import Product, ProductType
from database.models.subscription import Subscription, SubscriptionStatus

router = APIRouter(
    prefix="/admin/api",
    tags=["admin-monetization"],
    dependencies=[Depends(require_local_admin)],
)


def _bot(request: Request):
    return request.app.state.bot


def _guild(bot: Any, guild_id: int) -> discord.Guild:
    guild = bot.get_guild(guild_id)
    if guild is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "GUILD_NOT_FOUND", "message": "Servidor nao encontrado."}},
        )
    return guild


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def _format_brl(cents: int | None) -> str:
    if cents is None:
        return "R$ 0,00"
    return f"R$ {cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _format_price(cents: int | None) -> str | None:
    return _format_brl(cents) if cents is not None else None


def _format_discount(coupon: DiscountCoupon) -> str:
    if coupon.discount_type == DiscountType.PERCENTAGE:
        return f"{coupon.discount_value}%"
    return _format_brl(coupon.discount_value)


def _channel_missing(bot: Any, channel_id: int | None) -> bool:
    return channel_id is not None and bot.get_channel(channel_id) is None


def _role_missing(guild: discord.Guild, role_id: int | None) -> bool:
    return role_id is not None and guild.get_role(role_id) is None


def _role_name(guild: discord.Guild, role_id: int | None) -> str | None:
    if role_id is None:
        return None
    role = guild.get_role(role_id)
    return role.name if role is not None else None


def _metric(label: str, value: int | float | str, hint: str | None = None, source: str | None = None) -> MonetizationMetric:
    return MonetizationMetric(label=label, value=value, hint=hint, source=source)


def _alert(severity: str, title: str, message: str) -> MonetizationAlert:
    return MonetizationAlert(severity=severity, title=title, message=message)


@router.get("/guild/{guild_id}/monetization/summary", response_model=MonetizationSummaryResponse)
async def monetization_summary(request: Request, guild_id: int) -> MonetizationSummaryResponse:
    """Resumo seguro de monetizacao para a Fase 3.1/3.5.

    Varredura de seguranca desta subfase:
    - endpoint somente leitura;
    - nao altera pagamento, plano, cupom, cargo ou licenca;
    - nao recalcula preco de compra/cupom fora dos services;
    - nao expõe QR code PIX, checkout_url, payer_information, external_id ou secrets;
    - toda consulta multi-tenant fica limitada ao guild_id recebido;
    - Products sao globais, entao entram apenas quando vinculados a um Plan da guild
      ou quando o required_role_guild_id aponta para esta guild.
    """
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_30_days = now - timedelta(days=30)

    async with bot.database.session() as session:
        settings = await session.scalar(
            select(MonetizationSettings).where(MonetizationSettings.guild_id == guild_id)
        )
        plans = list(
            (
                await session.execute(
                    select(Plan).where(Plan.guild_id == guild_id).order_by(Plan.position.asc(), Plan.name.asc())
                )
            ).scalars().all()
        )
        coupons = list(
            (
                await session.execute(
                    select(DiscountCoupon).where(DiscountCoupon.guild_id == guild_id).order_by(DiscountCoupon.created_at.desc())
                )
            ).scalars().all()
        )
        plan_product_ids = [plan.product_id for plan in plans if plan.product_id is not None]
        product_filters = [Product.required_role_guild_id == guild_id]
        if plan_product_ids:
            product_filters.append(Product.id.in_(plan_product_ids))
        products = list(
            (
                await session.execute(
                    select(Product)
                    .where(Product.is_active.is_(True), or_(*product_filters))
                    .order_by(Product.position.asc())
                )
            ).scalars().all()
        )
        subscription_rows = (
            await session.execute(
                select(Subscription.plan_id, func.count(Subscription.id))
                .where(Subscription.guild_id == guild_id, Subscription.status == SubscriptionStatus.ACTIVE)
                .group_by(Subscription.plan_id)
            )
        ).all()
        active_subscriptions_by_plan = {plan_id: int(count or 0) for plan_id, count in subscription_rows}
        active_subscriptions = sum(active_subscriptions_by_plan.values())

        payment_plan_rows = (
            await session.execute(
                select(
                    PaymentHistory.plan_id,
                    PaymentHistory.status,
                    func.count(PaymentHistory.id),
                    func.coalesce(func.sum(PaymentHistory.amount), 0),
                    func.max(PaymentHistory.created_at),
                )
                .where(PaymentHistory.guild_id == guild_id)
                .group_by(PaymentHistory.plan_id, PaymentHistory.status)
            )
        ).all()
        status_rows = (
            await session.execute(
                select(
                    PaymentHistory.status,
                    func.count(PaymentHistory.id),
                    func.coalesce(func.sum(PaymentHistory.amount), 0),
                )
                .where(PaymentHistory.guild_id == guild_id)
                .group_by(PaymentHistory.status)
            )
        ).all()
        provider_rows = (
            await session.execute(
                select(PaymentHistory.provider, func.count(PaymentHistory.id), func.coalesce(func.sum(PaymentHistory.amount), 0))
                .where(PaymentHistory.guild_id == guild_id)
                .group_by(PaymentHistory.provider)
            )
        ).all()
        approved_revenue_month = int(
            await session.scalar(
                select(func.coalesce(func.sum(PaymentHistory.amount), 0)).where(
                    PaymentHistory.guild_id == guild_id,
                    PaymentHistory.status == PaymentStatus.APPROVED,
                    PaymentHistory.paid_at >= month_start,
                )
            )
            or 0
        )
        failed_payments_30d = int(
            await session.scalar(
                select(func.count(PaymentHistory.id)).where(
                    PaymentHistory.guild_id == guild_id,
                    PaymentHistory.created_at >= last_30_days,
                    PaymentHistory.status.in_(
                        [
                            PaymentStatus.REJECTED,
                            PaymentStatus.EXPIRED,
                            PaymentStatus.CANCELED,
                            PaymentStatus.CHARGEBACK,
                        ]
                    ),
                )
            )
            or 0
        )
        recent_rows = (
            await session.execute(
                select(PaymentHistory, Plan.name)
                .join(Plan, Plan.id == PaymentHistory.plan_id)
                .where(PaymentHistory.guild_id == guild_id)
                .order_by(PaymentHistory.created_at.desc())
                .limit(12)
            )
        ).all()

    active_plans = [plan for plan in plans if plan.is_active]
    active_coupons = [coupon for coupon in coupons if coupon.active and coupon.deleted_at is None]
    dlc_products = [product for product in products if product.product_type == ProductType.DLC]
    providers = sorted({provider for provider, _, _ in provider_rows if provider})

    payment_stats: dict[Any, dict[str, Any]] = {}
    for plan_id, status, count, amount, last_at in payment_plan_rows:
        stats = payment_stats.setdefault(plan_id, {"approved_sales": 0, "approved_revenue": 0, "pending": 0, "failed": 0, "last_payment_at": None})
        status_value = status.value if hasattr(status, "value") else str(status)
        count_int = int(count or 0)
        amount_int = int(amount or 0)
        if status == PaymentStatus.APPROVED:
            stats["approved_sales"] += count_int
            stats["approved_revenue"] += amount_int
        elif status in {PaymentStatus.PENDING, PaymentStatus.PROCESSING}:
            stats["pending"] += count_int
        elif status in {PaymentStatus.REJECTED, PaymentStatus.EXPIRED, PaymentStatus.CANCELED, PaymentStatus.CHARGEBACK, PaymentStatus.REFUNDED}:
            stats["failed"] += count_int
        if last_at is not None and (stats["last_payment_at"] is None or last_at > stats["last_payment_at"]):
            stats["last_payment_at"] = last_at
        stats[f"status_{status_value}"] = count_int

    approved_revenue_total = sum(int(stats["approved_revenue"]) for stats in payment_stats.values())
    approved_sales_total = sum(int(stats["approved_sales"]) for stats in payment_stats.values())
    pending_payments = sum(int(stats["pending"]) for stats in payment_stats.values())
    average_ticket = round(approved_revenue_total / approved_sales_total) if approved_sales_total else 0

    plan_rows: list[MonetizationPlanRow] = []
    for plan in plans:
        stats = payment_stats.get(plan.id, {"approved_sales": 0, "approved_revenue": 0, "pending": 0, "failed": 0, "last_payment_at": None})
        approved_sales = int(stats["approved_sales"])
        approved_revenue = int(stats["approved_revenue"])
        plan_rows.append(
            MonetizationPlanRow(
                id=str(plan.id),
                name=plan.name,
                active=plan.is_active,
                role_id=str(plan.role_id) if plan.role_id else None,
                role_name=_role_name(guild, plan.role_id),
                role_missing=_role_missing(guild, plan.role_id),
                price_monthly_label=_format_price(plan.price_monthly),
                price_yearly_label=_format_price(plan.price_yearly),
                price_one_time_label=_format_price(plan.price_one_time),
                approved_sales=approved_sales,
                approved_revenue_label=_format_brl(approved_revenue),
                approved_revenue_cents=approved_revenue,
                pending_payments=int(stats["pending"]),
                failed_payments=int(stats["failed"]),
                active_subscriptions=active_subscriptions_by_plan.get(plan.id, 0),
                average_ticket_label=_format_brl(round(approved_revenue / approved_sales) if approved_sales else 0),
                last_payment_at=_iso(stats["last_payment_at"]),
                source_note="payments: payment_history filtrado por guild_id e plan_id; assinaturas: subscriptions ACTIVE.",
            )
        )
    plan_rows.sort(key=lambda item: (item.approved_revenue_cents, item.approved_sales), reverse=True)

    top_seller = max(plan_rows, key=lambda item: item.approved_sales, default=None)
    top_revenue = max(plan_rows, key=lambda item: item.approved_revenue_cents, default=None)

    alerts: list[MonetizationAlert] = []
    if settings is None:
        alerts.append(_alert("warning", "Monetizacao sem configuracao", "A loja ainda nao tem configuracao geral salva para este servidor."))
    else:
        channel_checks = [
            ("Canal da loja", settings.shop_channel_id),
            ("Canal de aprovacao manual", settings.approval_channel_id),
            ("Canal de logs", settings.log_channel_id),
        ]
        for label, channel_id in channel_checks:
            if channel_id is None:
                alerts.append(_alert("warning", label, "Campo vazio nas configuracoes de monetizacao."))
            elif _channel_missing(bot, channel_id):
                alerts.append(_alert("error", label, f"Canal salvo ({channel_id}) nao existe mais no cache do Discord."))
        if settings.shop_channel_id is not None and settings.shop_message_id is None:
            alerts.append(_alert("warning", "Painel da loja nao publicado", "Existe canal da loja, mas nenhuma mensagem de loja salva."))

    for plan in active_plans:
        has_price = any(value is not None and value > 0 for value in [plan.price_monthly, plan.price_yearly, plan.price_one_time])
        if not has_price:
            alerts.append(_alert("warning", f"Plano sem preco: {plan.name}", "Plano ativo sem preco configurado nao deve aparecer como oferta valida."))
        if plan.role_id is not None and _role_missing(guild, plan.role_id):
            alerts.append(_alert("error", f"Cargo ausente no plano: {plan.name}", f"O cargo salvo ({plan.role_id}) nao existe mais no servidor."))

    if approved_revenue_total > 0 and not providers:
        alerts.append(_alert("info", "Receita sem provider visivel", "Existe valor aprovado no banco, mas sem provider recente para explicar a origem."))
    if approved_revenue_total > 0:
        alerts.append(_alert("info", "Receita aprovada registrada", "Este valor vem de payment_history.status=approved. Pode incluir teste, manual ou venda real; veja os pagamentos recentes e a tabela por plano."))
    if not active_plans:
        alerts.append(_alert("warning", "Nenhum plano ativo", "A loja pode ficar vazia se nao houver planos ativos."))
    if pending_payments > 10:
        alerts.append(_alert("warning", "Muitos pagamentos pendentes", "Verifique se o gateway/manual esta processando as cobrancas normalmente."))
    if failed_payments_30d > 0:
        alerts.append(_alert("info", "Pagamentos recusados recentes", f"{failed_payments_30d} pagamento(s) falharam, expiraram ou foram cancelados nos ultimos 30 dias."))

    return MonetizationSummaryResponse(
        guild_id=str(guild_id),
        generated_at=_iso(now) or "",
        gateway={
            "providers_seen": providers,
            "provider_breakdown": [
                {"provider": provider, "count": int(count or 0), "amount_label": _format_brl(int(amount or 0))}
                for provider, count, amount in provider_rows
            ],
            "mode": ", ".join(providers) if providers else "Sem pagamentos recentes",
            "read_only": True,
        },
        metrics=[
            _metric("Receita aprovada registrada", _format_brl(approved_revenue_total), "Soma de payment_history APPROVED", "payment_history.amount where guild_id/status=approved"),
            _metric("Receita aprovada no mes", _format_brl(approved_revenue_month), "Pagamentos aprovados com paid_at neste mes", "payment_history.paid_at"),
            _metric("Vendas aprovadas", approved_sales_total, "Quantidade de registros APPROVED", "payment_history.status"),
            _metric("Ticket medio", _format_brl(average_ticket), "Receita aprovada / vendas aprovadas", "calculado a partir de payment_history"),
            _metric("Planos ativos", len(active_plans), f"{len(plans)} plano(s) no total", "plans.is_active"),
            _metric("Assinaturas ativas", active_subscriptions, "Status ACTIVE", "subscriptions.status"),
            _metric("Pagamentos pendentes", pending_payments, "PENDING/PROCESSING", "payment_history.status"),
            _metric("Cupons ativos", len(active_coupons), f"{len(coupons)} cupom(ns) no total", "discount_coupons.active/deleted_at"),
            _metric("Produtos ativos", len(products), f"{len(dlc_products)} DLC(s) ativa(s)", "products ligados aos plans/cargos da guild"),
            _metric("Falhas 30d", failed_payments_30d, "Rejected/expired/canceled/chargeback", "payment_history.created_at/status"),
        ],
        alerts=alerts,
        recent_payments=[
            MonetizationRecentPayment(
                id=str(payment.id),
                user_id=str(payment.user_id),
                plan_id=str(payment.plan_id),
                plan_name=plan_name,
                provider=payment.provider,
                amount_label=_format_brl(payment.amount),
                amount_cents=payment.amount,
                status=payment.status.value,
                created_at=_iso(payment.created_at) or "",
                paid_at=_iso(payment.paid_at),
                expires_at=_iso(payment.expires_at),
            )
            for payment, plan_name in recent_rows
        ],
        plans=plan_rows,
        payment_status_breakdown=[
            MonetizationStatusBreakdown(
                status=status.value if hasattr(status, "value") else str(status),
                count=int(count or 0),
                amount_label=_format_brl(int(amount or 0)),
                amount_cents=int(amount or 0),
            )
            for status, count, amount in status_rows
        ],
        coupons=[
            MonetizationCouponRow(
                id=str(coupon.id),
                code=coupon.code,
                active=coupon.active,
                deleted=coupon.deleted_at is not None,
                discount=_format_discount(coupon),
                starts_at=_iso(coupon.starts_at),
                expires_at=_iso(coupon.expires_at),
                source_note="discount_coupons da guild; 0 ativos e 1 total significa cupom inativo ou deletado logico.",
            )
            for coupon in coupons
        ],
        analytics={
            "top_seller_plan": top_seller.name if top_seller and top_seller.approved_sales > 0 else None,
            "top_revenue_plan": top_revenue.name if top_revenue and top_revenue.approved_revenue_cents > 0 else None,
            "approved_sales_total": approved_sales_total,
            "approved_revenue_total_cents": approved_revenue_total,
            "average_ticket_cents": average_ticket,
            "read_only": True,
        },
        source_notes=[
            "5 planos no total = todas as linhas da tabela plans para esta guild, incluindo inativos.",
            "Receita aprovada registrada = soma de payment_history.amount com status approved; nao prova sozinha que foi venda real.",
            "1 cupom no total = linha existente em discount_coupons; se ativos=0, ele esta inativo ou deletado logico.",
            "Planos ativos = plans.is_active=True; assinaturas ativas = subscriptions.status=ACTIVE.",
            "O dashboard nao usa cargos atuais do Discord para inventar vendas; ele mostra apenas registros do banco.",
        ],
        security_notes=[
            "Fase 3.1/3.5 continua somente leitura.",
            "Nao retorna pix_qr_code, pix_qr_code_base64, checkout_url, payer_information, external_id nem secrets.",
            "Nao altera PaymentHistory, Subscription, Plan, Product, Coupon, License ou cargos do Discord.",
            "Acoes de escrita ficam para 3.2+ e devem passar pelos services existentes.",
        ],
    )
