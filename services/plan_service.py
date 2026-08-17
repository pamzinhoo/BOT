from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import discord

from core.logger import get_logger
from database.database import Database
from database.models.audit_log import AuditLogCategory
from database.models.discount_coupon import DiscountCoupon, DiscountType
from database.models.plan import Plan
from database.models.plan_benefit import PlanBenefit
from database.models.plan_message import PlanMessage, PlanMessageType
from database.repositories.plan_repository import (
    PlanBenefitRepository,
    PlanMessageRepository,
    PlanRepository,
)
from database.repositories.vote_weight_repository import VoteWeightRepository

if TYPE_CHECKING:
    from core.bot import LimerenceBot

logger = get_logger("plan_service")


def render_placeholders(
    template: str,
    *,
    member: discord.Member | discord.User | None = None,
    guild: discord.Guild | None = None,
    plan: Plan | None = None,
    role: discord.Role | None = None,
    renew_date: datetime | None = None,
    expires_at: datetime | None = None,
    days_left: int | None = None,
    grace_days: int | None = None,
    renew_link: str | None = None,
    renew_command: str | None = None,
    store_command: str | None = None,
    subscription_id: object | None = None,
    coupon: DiscountCoupon | None = None,
    discount_amount: int | None = None,
    original_price: int | None = None,
    final_price: int | None = None,
    remaining_uses: int | None = None,
    currency: str = "BRL",
    payment_id: object | None = None,
    status: str | None = None,
    staff: discord.Member | discord.User | None = None,
    date: datetime | None = None,
    ticket_type: str | None = None,
    claimed_by: str | None = None,
    closed_by: str | None = None,
    opened_at: str | None = None,
    closed_at: str | None = None,
    ticket_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Substitui placeholders em mensagens/descricoes 100% editaveis pelo admin.
    Preparado pra novos placeholders: basta acrescentar uma entrada no dict.

    Os kwargs extras (expires_at/days_left/grace_days/renew_*/store_command/
    subscription_id) sao usados pelas mensagens de renovacao de assinatura; em
    qualquer outro contexto ficam None e o placeholder vira "—".

    Os kwargs de cupom (coupon/discount_amount/original_price/final_price/
    remaining_uses) alimentam {coupon} {discount} {discount_type}
    {discount_value} {original_price} {final_price} {remaining_uses} nas telas
    de compra com desconto. `remaining_uses=None` vira "∞" (cupom sem limite
    global), coerente com a UI de Limites.

    `{user}` continua sendo a mencao do membro (comportamento historico das
    mensagens de Plano/Booster) e `{mention}` e um alias explicito dele — assim
    nenhuma mensagem ja cadastrada muda de significado."""
    user_mention = member.mention if member is not None else "—"
    staff_mention = staff.mention if staff is not None else "—"
    values = {
        "{user}": user_mention,
        "{mention}": user_mention,
        "{server_name}": guild.name if guild is not None else "—",
        "{guild}": guild.name if guild is not None else "—",
        "{server}": guild.name if guild is not None else "—",
        # avaliacao de tickets (ver services/evaluation_service.py,
        # views/ticket_actions_view.py) — sem contexto, todos viram "—" como
        # os demais placeholders acima.
        "{ticket_type}": ticket_type or "—",
        "{category}": ticket_type or "—",
        "{claimed_by}": claimed_by or "—",
        "{closed_by}": closed_by or "—",
        "{opened_at}": opened_at or "—",
        "{closed_at}": closed_at or "—",
        "{ticket_id}": ticket_id or "—",
        "{reason}": reason or "—",
        "{plan_name}": plan.name if plan is not None else "—",
        "{plan}": plan.name if plan is not None else "—",
        "{plan_emoji}": (plan.emoji or "") if plan is not None else "",
        "{plan_price}": _format_price(plan) if plan is not None else "—",
        "{price}": _format_price(plan) if plan is not None else "—",
        "{payment_id}": str(payment_id) if payment_id is not None else "—",
        "{status}": status or "—",
        "{staff}": staff_mention,
        "{staff_mention}": staff_mention,
        "{date}": date.strftime("%d/%m/%Y") if date is not None else "—",
        "{role_name}": role.mention if role is not None else "—",
        "{renew_date}": renew_date.strftime("%d/%m/%Y") if renew_date is not None else "—",
        "{expires_at}": expires_at.strftime("%d/%m/%Y") if expires_at is not None else "—",
        "{days_left}": str(days_left) if days_left is not None else "—",
        "{grace_days}": str(grace_days) if grace_days is not None else "—",
        "{renew_link}": renew_link or "—",
        "{renew_command}": renew_command or "/assinatura ver",
        "{store_command}": store_command or "/loja",
        "{subscription_id}": str(subscription_id) if subscription_id is not None else "—",
        "{guild_members}": str(guild.member_count) if guild is not None else "—",
        "{coupon}": coupon.code if coupon is not None else "—",
        "{discount}": _format_discount(coupon, discount_amount, currency),
        "{discount_type}": _DISCOUNT_TYPE_LABELS.get(coupon.discount_type, "—")
        if coupon is not None
        else "—",
        "{discount_value}": str(coupon.discount_value) if coupon is not None else "—",
        "{original_price}": _format_cents(original_price, currency),
        "{final_price}": _format_cents(final_price, currency),
        # sem contexto de cupom nenhum o placeholder vira "—" como todos os
        # outros; com cupom e sem limite global, vira "∞".
        "{remaining_uses}": str(remaining_uses)
        if remaining_uses is not None
        else ("∞" if coupon is not None else "—"),
    }
    result = template
    for placeholder, value in values.items():
        result = result.replace(placeholder, value)
    return result


_DISCOUNT_TYPE_LABELS = {
    DiscountType.PERCENTAGE: "Porcentagem",
    DiscountType.FIXED: "Valor fixo",
}


def _format_cents(cents: int | None, currency: str) -> str:
    if cents is None:
        return "—"
    return f"{currency} {cents / 100:.2f}"


def _format_discount(
    coupon: DiscountCoupon | None, discount_amount: int | None, currency: str
) -> str:
    """Prioriza o desconto REAL aplicado (em centavos) quando ele existe; senao
    descreve o desconto configurado no cupom ("20%" ou "BRL 5,00")."""
    if discount_amount is not None:
        return _format_cents(discount_amount, currency)
    if coupon is None:
        return "—"
    if coupon.discount_type == DiscountType.PERCENTAGE:
        return f"{coupon.discount_value}%"
    return _format_cents(coupon.discount_value, currency)


def _format_price(plan: Plan) -> str:
    price = plan.price_monthly or plan.price_yearly or plan.price_one_time
    if price is None:
        return "—"
    return f"{plan.currency} {price / 100:.2f}"


class PlanService:
    """Regras de negocio do cadastro de Planos/Beneficios/Mensagens — nenhum
    valor fixo, tudo lido do banco por guild. Cogs/Views nunca tocam nos
    repositorios diretamente, so este servico."""

    def __init__(self, database: Database, bot: LimerenceBot | None = None) -> None:
        self._database = database
        self._bot = bot

    # --- planos -----------------------------------------------------------

    async def list_plans(self, guild_id: int, *, only_active: bool = False) -> list[Plan]:
        async with self._database.session() as session:
            return await PlanRepository(session).list_by_guild(guild_id, only_active=only_active)

    async def get_plan(self, plan_id: uuid.UUID) -> Plan | None:
        async with self._database.session() as session:
            return await PlanRepository(session).get_by_id(plan_id)

    async def create_plan(
        self,
        guild_id: int,
        name: str,
        *,
        executor: discord.Member | discord.User | None = None,
    ) -> Plan:
        async with self._database.session() as session:
            repo = PlanRepository(session)
            plans = await repo.list_by_guild(guild_id)
            if any(p.name == name for p in plans):
                raise ValueError(f"Já existe um plano chamado '{name}' neste servidor.")
            plan = Plan(guild_id=guild_id, name=name, position=len(plans))
            plan = await repo.add(plan)
        await self._audit(guild_id, action="Plano criado", executor=executor, details={"plano": name})
        return plan

    async def update_plan(
        self,
        plan_id: uuid.UUID,
        *,
        executor: discord.Member | discord.User | None = None,
        **fields: object,
    ) -> Plan:
        async with self._database.session() as session:
            repo = PlanRepository(session)
            plan = await repo.get_by_id(plan_id)
            if plan is None:
                raise ValueError("Plano não encontrado.")
            for key, value in fields.items():
                setattr(plan, key, value)
            await session.flush()
            await session.refresh(plan)
        await self._audit(
            plan.guild_id, action="Plano editado", executor=executor,
            details={"plano": plan.name, "campos": list(fields.keys())},
        )
        return plan

    async def delete_plan(
        self,
        plan_id: uuid.UUID,
        *,
        executor: discord.Member | discord.User | None = None,
    ) -> None:
        async with self._database.session() as session:
            repo = PlanRepository(session)
            plan = await repo.get_by_id(plan_id)
            if plan is None:
                return
            # sem isso, o FK ondelete=SET NULL so zera source_plan_id e deixa
            # a linha de peso orfa (source="PLAN_BENEFIT" sem plano nenhum)
            weight_repo = VoteWeightRepository(session)
            for weight in await weight_repo.list_by_source_plan(plan_id):
                await weight_repo.delete(weight)
            await repo.delete(plan)
        await self._audit(
            plan.guild_id, action="Plano removido", executor=executor, details={"plano": plan.name}
        )

    # --- beneficios ---------------------------------------------------------

    async def list_benefits(self, plan_id: uuid.UUID) -> list[PlanBenefit]:
        async with self._database.session() as session:
            return await PlanBenefitRepository(session).list_by_plan(plan_id)

    async def map_benefits(self, plan_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[PlanBenefit]]:
        """Batch de list_benefits — 1 query pra N planos em vez de N queries
        (ver PlanBenefitRepository.map_by_plans)."""
        async with self._database.session() as session:
            return await PlanBenefitRepository(session).map_by_plans(plan_ids)

    async def add_benefit(
        self,
        plan_id: uuid.UUID,
        text: str,
        *,
        executor: discord.Member | discord.User | None = None,
    ) -> PlanBenefit:
        async with self._database.session() as session:
            repo = PlanBenefitRepository(session)
            existing = await repo.list_by_plan(plan_id)
            benefit = PlanBenefit(plan_id=plan_id, text=text, position=len(existing))
            benefit = await repo.add(benefit)
            plan = await PlanRepository(session).get_by_id(plan_id)
        if plan is not None:
            await self._audit(
                plan.guild_id, action="Benefício adicionado", executor=executor,
                details={"plano": plan.name, "beneficio": text},
            )
        return benefit

    async def remove_benefit(
        self,
        benefit_id: uuid.UUID,
        *,
        executor: discord.Member | discord.User | None = None,
    ) -> None:
        async with self._database.session() as session:
            repo = PlanBenefitRepository(session)
            benefit = await repo.get_by_id(benefit_id)
            if benefit is None:
                return
            await repo.delete(benefit)
            plan = await PlanRepository(session).get_by_id(benefit.plan_id)
        if plan is not None:
            await self._audit(
                plan.guild_id, action="Benefício removido", executor=executor,
                details={"plano": plan.name, "beneficio": benefit.text},
            )

    async def set_benefits(
        self,
        plan_id: uuid.UUID,
        texts: list[str],
        *,
        executor: discord.Member | discord.User | None = None,
    ) -> list[PlanBenefit]:
        """Substitui a lista inteira de beneficios de um plano — usado pelo
        editor de texto multi-linha do painel (1 linha por beneficio)."""
        async with self._database.session() as session:
            repo = PlanBenefitRepository(session)
            await repo.delete_all_for_plan(plan_id)
            created = []
            for position, text in enumerate(t.strip() for t in texts if t.strip()):
                created.append(await repo.add(PlanBenefit(plan_id=plan_id, text=text, position=position)))
            plan = await PlanRepository(session).get_by_id(plan_id)
        if plan is not None:
            await self._audit(
                plan.guild_id, action="Benefícios atualizados", executor=executor,
                details={"plano": plan.name, "total": len(created)},
            )
        return created

    # --- auditoria ------------------------------------------------------

    async def _audit(
        self,
        guild_id: int,
        *,
        action: str,
        executor: discord.Member | discord.User | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        """Acoplamento opcional com o bot (igual CouponService._audit_raw):
        sem bot montado (testes), o fluxo segue igual."""
        if self._bot is None:
            return
        try:
            await self._bot.audit_log_service.record(
                guild_id=guild_id,
                category=AuditLogCategory.PLAN,
                action=action,
                executor_id=executor.id if executor else None,
                executor_name=str(executor) if executor else None,
                details=details or {},
            )
        except Exception:
            logger.exception("Falha ao auditar evento de plano '%s' na guild %s.", action, guild_id)

    # --- mensagens ------------------------------------------------------

    async def get_message(self, plan_id: uuid.UUID, message_type: PlanMessageType) -> PlanMessage | None:
        async with self._database.session() as session:
            return await PlanMessageRepository(session).get_by_plan_and_type(plan_id, message_type)

    async def list_messages(self, plan_id: uuid.UUID) -> list[PlanMessage]:
        async with self._database.session() as session:
            return await PlanMessageRepository(session).list_by_plan(plan_id)

    async def set_message(
        self, plan_id: uuid.UUID, message_type: PlanMessageType, content: str
    ) -> PlanMessage:
        async with self._database.session() as session:
            repo = PlanMessageRepository(session)
            existing = await repo.get_by_plan_and_type(plan_id, message_type)
            if existing is not None:
                existing.content = content
                await session.flush()
                return existing
            return await repo.add(
                PlanMessage(plan_id=plan_id, message_type=message_type, content=content)
            )
