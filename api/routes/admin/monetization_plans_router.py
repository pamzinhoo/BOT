from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import discord
from fastapi import APIRouter, Depends, HTTPException, Request

from api.routes.admin.security import require_local_admin
from api.schemas.admin import (
    MonetizationPlanListResponse,
    MonetizationPlanManageRow,
    MonetizationPlanMutationRequest,
    MonetizationPlanMutationResponse,
)
from database.models.plan import Plan

router = APIRouter(
    prefix="/admin/api",
    tags=["admin-monetization-plans"],
    dependencies=[Depends(require_local_admin)],
)

_DASHBOARD_ACTOR = "Painel web"
_MAX_PLAN_PRICE_CENTS = 1_000_000


class _DashboardExecutor:
    id = 0

    def __str__(self) -> str:
        return _DASHBOARD_ACTOR


_DASHBOARD_EXECUTOR = _DashboardExecutor()


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


def _payload_error(message: str, field: str | None = None) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"error": {"code": "INVALID_PLAN", "message": message, "field": field}},
    )


def _format_brl(cents: int | None) -> str | None:
    if cents is None:
        return None
    return f"R$ {cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _clean_text(raw: Any, field: str, *, required: bool, max_len: int) -> str | None:
    value = str(raw or "").strip()
    if required and not value:
        raise _payload_error("Campo obrigatorio.", field)
    if len(value) > max_len:
        raise _payload_error(f"Use no maximo {max_len} caracteres.", field)
    return value or None


def _price_cents(raw: Any, field: str) -> int | None:
    value = str(raw or "").strip().replace(",", ".")
    if not value:
        return None
    try:
        cents = int((Decimal(value) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError) as exc:
        raise _payload_error("Preco invalido.", field) from exc
    if cents <= 0:
        raise _payload_error("Preco precisa ser maior que zero ou ficar vazio.", field)
    if cents > _MAX_PLAN_PRICE_CENTS:
        raise _payload_error("Preco muito alto para o painel web.", field)
    return cents


def _role_id(guild: discord.Guild, raw: Any) -> int | None:
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        role_id = int(value)
    except ValueError as exc:
        raise _payload_error("Cargo invalido.", "role_id") from exc
    role = guild.get_role(role_id)
    if role is None or role.is_default():
        raise _payload_error("Escolha um cargo existente e valido neste servidor.", "role_id")
    return role_id


def _role_name(guild: discord.Guild, role_id: int | None) -> str | None:
    if role_id is None:
        return None
    role = guild.get_role(role_id)
    return role.name if role is not None else None


def _serialize_plan(guild: discord.Guild, plan: Plan) -> MonetizationPlanManageRow:
    return MonetizationPlanManageRow(
        id=str(plan.id),
        name=plan.name,
        description=plan.description,
        emoji=plan.emoji,
        role_id=str(plan.role_id) if plan.role_id else None,
        role_name=_role_name(guild, plan.role_id),
        role_missing=plan.role_id is not None and guild.get_role(plan.role_id) is None,
        price_monthly_amount=plan.price_monthly,
        price_yearly_amount=plan.price_yearly,
        price_one_time_amount=plan.price_one_time,
        price_monthly_label=_format_brl(plan.price_monthly),
        price_yearly_label=_format_brl(plan.price_yearly),
        price_one_time_label=_format_brl(plan.price_one_time),
        currency=plan.currency,
        position=plan.position,
        is_recommended=plan.is_recommended,
        is_active=plan.is_active,
        product_id=str(plan.product_id) if plan.product_id else None,
        created_at=plan.created_at.isoformat() if plan.created_at else None,
        updated_at=plan.updated_at.isoformat() if plan.updated_at else None,
    )


def _security_notes() -> list[str]:
    return [
        "Fase 3.2: usa PlanService para criar/editar planos.",
        "Nao altera PaymentHistory, Subscription, License, Product ou cargos do Discord.",
        "Nao apaga plano fisicamente; ativar/desativar preserva historico financeiro.",
        "Cargo e precos sao validados antes de salvar.",
    ]


async def _get_owned_plan(bot: Any, guild_id: int, plan_id: uuid.UUID) -> Plan:
    plan = await bot.plan_service.get_plan(plan_id)
    if plan is None or plan.guild_id != guild_id:
        raise HTTPException(status_code=404, detail={"error": {"code": "PLAN_NOT_FOUND", "message": "Plano nao encontrado."}})
    return plan


async def _refresh_shop_panel(bot: Any, guild_id: int) -> bool:
    painel_service = getattr(bot, "painel_service", None)
    refresh = getattr(painel_service, "refresh_shop_panel", None)
    if refresh is None:
        return False
    try:
        await refresh(guild_id)
        return True
    except Exception:
        return False


def _mutation_fields(guild: discord.Guild, payload: MonetizationPlanMutationRequest, *, existing: Plan | None = None) -> dict[str, object]:
    fields: dict[str, object] = {}
    if payload.name is not None:
        fields["name"] = _clean_text(payload.name, "name", required=True, max_len=100)
    if payload.description is not None:
        fields["description"] = _clean_text(payload.description, "description", required=False, max_len=1500)
    if payload.emoji is not None:
        fields["emoji"] = _clean_text(payload.emoji, "emoji", required=False, max_len=64)
    if payload.role_id is not None:
        fields["role_id"] = _role_id(guild, payload.role_id)
    if payload.price_monthly_reais is not None:
        fields["price_monthly"] = _price_cents(payload.price_monthly_reais, "price_monthly_reais")
    if payload.price_yearly_reais is not None:
        fields["price_yearly"] = _price_cents(payload.price_yearly_reais, "price_yearly_reais")
    if payload.price_one_time_reais is not None:
        fields["price_one_time"] = _price_cents(payload.price_one_time_reais, "price_one_time_reais")
    if payload.position is not None:
        if payload.position < 0 or payload.position > 500:
            raise _payload_error("Posicao invalida.", "position")
        fields["position"] = payload.position
    if payload.is_recommended is not None:
        fields["is_recommended"] = payload.is_recommended
    if payload.is_active is not None:
        fields["is_active"] = payload.is_active

    future_monthly = fields.get("price_monthly", existing.price_monthly if existing is not None else None)
    future_yearly = fields.get("price_yearly", existing.price_yearly if existing is not None else None)
    future_one_time = fields.get("price_one_time", existing.price_one_time if existing is not None else None)
    future_active = bool(fields.get("is_active", existing.is_active if existing is not None else True))
    if future_active and not any([future_monthly, future_yearly, future_one_time]):
        raise _payload_error("Plano ativo precisa ter pelo menos um preco.", "price_monthly_reais")
    return fields


@router.get("/guild/{guild_id}/monetization/plans/manage", response_model=MonetizationPlanListResponse)
async def list_manageable_plans(request: Request, guild_id: int) -> MonetizationPlanListResponse:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    plans = await bot.plan_service.list_plans(guild_id)
    return MonetizationPlanListResponse(
        guild_id=str(guild_id),
        items=[_serialize_plan(guild, plan) for plan in plans],
        security_notes=_security_notes(),
    )


@router.post("/guild/{guild_id}/monetization/plans", response_model=MonetizationPlanMutationResponse)
async def create_plan(request: Request, guild_id: int, payload: MonetizationPlanMutationRequest) -> MonetizationPlanMutationResponse:
    """Cria plano com PlanService e valida preco/cargo antes de publicar na loja."""
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    name = _clean_text(payload.name, "name", required=True, max_len=100) or "Plano"
    fields = _mutation_fields(guild, payload)
    try:
        plan = await bot.plan_service.create_plan(guild_id, name, executor=_DASHBOARD_EXECUTOR)
        fields.pop("name", None)
        if fields:
            plan = await bot.plan_service.update_plan(plan.id, executor=_DASHBOARD_EXECUTOR, **fields)
    except ValueError as exc:
        raise _payload_error(str(exc), "name") from exc
    shop_refresh_attempted = await _refresh_shop_panel(bot, guild_id)
    return MonetizationPlanMutationResponse(
        item=_serialize_plan(guild, plan),
        shop_refresh_attempted=shop_refresh_attempted,
        security_notes=_security_notes(),
    )


@router.patch("/guild/{guild_id}/monetization/plans/{plan_id}", response_model=MonetizationPlanMutationResponse)
async def update_plan(request: Request, guild_id: int, plan_id: uuid.UUID, payload: MonetizationPlanMutationRequest) -> MonetizationPlanMutationResponse:
    """Edita plano existente sem tocar em pagamentos, assinaturas ou licencas."""
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    existing = await _get_owned_plan(bot, guild_id, plan_id)
    fields = _mutation_fields(guild, payload, existing=existing)
    if not fields:
        return MonetizationPlanMutationResponse(item=_serialize_plan(guild, existing), security_notes=_security_notes())
    try:
        plan = await bot.plan_service.update_plan(plan_id, executor=_DASHBOARD_EXECUTOR, **fields)
    except ValueError as exc:
        raise _payload_error(str(exc)) from exc
    shop_refresh_attempted = await _refresh_shop_panel(bot, guild_id)
    return MonetizationPlanMutationResponse(
        item=_serialize_plan(guild, plan),
        shop_refresh_attempted=shop_refresh_attempted,
        security_notes=_security_notes(),
    )


@router.post("/guild/{guild_id}/monetization/plans/{plan_id}/toggle", response_model=MonetizationPlanMutationResponse)
async def toggle_plan(request: Request, guild_id: int, plan_id: uuid.UUID, payload: MonetizationPlanMutationRequest) -> MonetizationPlanMutationResponse:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    existing = await _get_owned_plan(bot, guild_id, plan_id)
    if payload.is_active is None:
        raise _payload_error("Informe is_active.", "is_active")
    fields = _mutation_fields(guild, MonetizationPlanMutationRequest(is_active=payload.is_active), existing=existing)
    plan = await bot.plan_service.update_plan(plan_id, executor=_DASHBOARD_EXECUTOR, **fields)
    shop_refresh_attempted = await _refresh_shop_panel(bot, guild_id)
    return MonetizationPlanMutationResponse(
        item=_serialize_plan(guild, plan),
        shop_refresh_attempted=shop_refresh_attempted,
        security_notes=_security_notes(),
    )
