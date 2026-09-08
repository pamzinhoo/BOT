from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import discord
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select

from api.routes.admin.security import require_local_admin
from api.schemas.admin import (
    MonetizationAlert,
    MonetizationMetric,
    MonetizationRecentPayment,
    MonetizationSummaryResponse,
)
from database.models.discount_coupon import DiscountCoupon
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


def _channel_missing(bot: Any, channel_id: int | None) -> bool:
    return channel_id is not None and bot.get_channel(channel_id) is None


def _role_missing(guild: discord.Guild, role_id: int | None) -> bool:
    return role_id is not None and guild.get_role(role_id) is None


def _metric(label: str, value: int | float | str, hint: str | None = None) -> MonetizationMetric:
    return MonetizationMetric(label=label, value=value, hint=hint)


def _alert(severity: str, title: str, message: str) -> MonetizationAlert:
    return MonetizationAlert(severity=severity, title=title, message=message)


@router.get("/guild/{guild_id}/monetization/summary", response_model=MonetizationSummaryResponse)
async def monetization_summary(request: Request, guild_id: int) -> MonetizationSummaryResponse:
    """Resumo seguro de monetizacao para a Fase 3.1.

    Varredura de seguranca desta subfase:
    - endpoint somente leitura;
    - nao altera pagamento, plano, cupom, cargo ou licenca;
    - nao recalcula preco de compra/cupom fora dos services;
    - nao expõe QR code PIX, checkout_url, payer_information ou secrets;
    - toda consulta fica limitada ao guild_id recebido.
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
                    select(DiscountCoupon).where(DiscountCoupon.guild_id == guild_id)
                )
            ).scalars().all()
        )
        products = list(
            (
                await session.execute(
                    select(Product).where(Product.is_active.is_(True)).order_by(Product.position.asc())
                )
            ).scalars().all()
        )
        active_subscriptions = int(
            await session.scalar(
                select(func.count(Subscription.id)).where(
                    Subscription.guild_id == guild_id,
                    Subscription.status == SubscriptionStatus.ACTIVE,
                )
            )
            or 0
        )
        approved_revenue_total = int(
            await session.scalar(
                select(func.coalesce(func.sum(PaymentHistory.amount), 0)).where(
                    PaymentHistory.guild_id == guild_id,
                    PaymentHistory.status == PaymentStatus.APPROVED,
                )
            )
            or 0
        )
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
        pending_payments = int(
            await session.scalar(
                select(func.count(PaymentHistory.id)).where(
                    PaymentHistory.guild_id == guild_id,
                    PaymentHistory.status.in_([PaymentStatus.PENDING, PaymentStatus.PROCESSING]),
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
                .limit(8)
            )
        ).all()

    active_plans = [plan for plan in plans if plan.is_active]
    active_coupons = [coupon for coupon in coupons if coupon.active and coupon.deleted_at is None]
    dlc_products = [product for product in products if product.product_type == ProductType.DLC]
    providers = sorted({payment.provider for payment, _ in recent_rows if payment.provider})
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
            "mode": ", ".join(providers) if providers else "Sem pagamentos recentes",
            "read_only": True,
        },
        metrics=[
            _metric("Receita aprovada total", _format_brl(approved_revenue_total), "Somente pagamentos aprovados"),
            _metric("Receita aprovada no mes", _format_brl(approved_revenue_month), "Desde o primeiro dia do mes"),
            _metric("Planos ativos", len(active_plans), f"{len(plans)} plano(s) no total"),
            _metric("Assinaturas ativas", active_subscriptions, "Status ACTIVE"),
            _metric("Pagamentos pendentes", pending_payments, "PENDING/PROCESSING"),
            _metric("Cupons ativos", len(active_coupons), f"{len(coupons)} cupom(ns) no total"),
            _metric("Produtos ativos", len(products), f"{len(dlc_products)} DLC(s) ativa(s)"),
            _metric("Falhas 30d", failed_payments_30d, "Rejected/expired/canceled/chargeback"),
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
                status=payment.status.value,
                created_at=_iso(payment.created_at) or "",
                paid_at=_iso(payment.paid_at),
                expires_at=_iso(payment.expires_at),
            )
            for payment, plan_name in recent_rows
        ],
        security_notes=[
            "Fase 3.1 e somente leitura.",
            "Nao retorna pix_qr_code, pix_qr_code_base64, checkout_url, payer_information nem secrets.",
            "Nao altera PaymentHistory, Subscription, Plan, Product, Coupon, License ou cargos do Discord.",
            "Acoes de escrita ficam para 3.2+ e devem passar pelos services existentes.",
        ],
    )
