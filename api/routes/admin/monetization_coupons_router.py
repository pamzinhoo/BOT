from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import discord
from fastapi import APIRouter, Depends, HTTPException, Request

from api.routes.admin.security import require_local_admin
from api.schemas.admin import (
    MonetizationCouponListResponse,
    MonetizationCouponManageRow,
    MonetizationCouponMutationRequest,
    MonetizationCouponMutationResponse,
)
from database.models.audit_log import AuditLogCategory
from database.models.discount_coupon import DiscountCoupon, DiscountType
from database.models.subscription import BillingCycle
from services.coupon_service import CouponError, normalize_code

router = APIRouter(
    prefix="/admin/api",
    tags=["admin-monetization-coupons"],
    dependencies=[Depends(require_local_admin)],
)

_MAX_FIXED_DISCOUNT_CENTS = 1_000_000
_MAX_TEXT = 1500
_MAX_CODE = 64
_DASHBOARD_ACTOR = "Painel web"


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
        detail={"error": {"code": "INVALID_COUPON", "message": message, "field": field}},
    )


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def _clean_text(raw: Any, field: str, *, required: bool = False, max_len: int = _MAX_TEXT) -> str | None:
    value = str(raw or "").strip()
    if required and not value:
        raise _payload_error("Campo obrigatorio.", field)
    if len(value) > max_len:
        raise _payload_error(f"Use no maximo {max_len} caracteres.", field)
    return value or None


def _parse_datetime(raw: str | None, field: str) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _payload_error("Data invalida.", field) from exc
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _role_id(guild: discord.Guild, raw: str | None) -> int | None:
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        role_id = int(value)
    except ValueError as exc:
        raise _payload_error("Cargo invalido.", "required_role_id") from exc
    role = guild.get_role(role_id)
    if role is None or role.is_default():
        raise _payload_error("Escolha um cargo existente e valido neste servidor.", "required_role_id")
    return role_id


def _role_name(guild: discord.Guild, role_id: int | None) -> str | None:
    if role_id is None:
        return None
    role = guild.get_role(role_id)
    return role.name if role is not None else None


def _discount_type(raw: str | None, existing: DiscountType | None = None) -> DiscountType:
    if raw is None:
        return existing or DiscountType.PERCENTAGE
    try:
        return DiscountType(raw)
    except ValueError as exc:
        raise _payload_error("Tipo de desconto invalido.", "discount_type") from exc


def _discount_value(raw: str | None, discount_type: DiscountType, field: str = "discount_value") -> int:
    value = str(raw or "").strip().replace(",", ".")
    if not value:
        raise _payload_error("Informe o valor do desconto.", field)
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise _payload_error("Desconto invalido.", field) from exc
    if discount_type == DiscountType.PERCENTAGE:
        if number != number.to_integral_value() or number < 1 or number > 100:
            raise _payload_error("Porcentagem precisa ser um numero inteiro de 1 a 100.", field)
        return int(number)
    cents = int((number * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if cents <= 0:
        raise _payload_error("Valor fixo precisa ser maior que zero.", field)
    if cents > _MAX_FIXED_DISCOUNT_CENTS:
        raise _payload_error("Valor fixo muito alto para o painel web.", field)
    return cents


def _format_brl(cents: int) -> str:
    return f"R$ {cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _discount_label(coupon: DiscountCoupon) -> str:
    if coupon.discount_type == DiscountType.PERCENTAGE:
        return f"{coupon.discount_value}%"
    return _format_brl(coupon.discount_value)


def _discount_value_reais(coupon: DiscountCoupon) -> str | None:
    if coupon.discount_type != DiscountType.FIXED:
        return None
    return f"{coupon.discount_value / 100:.2f}".replace(".", ",")


def _limit(raw: int | None, field: str) -> int | None:
    if raw is None:
        return None
    if raw < 1 or raw > 1_000_000:
        raise _payload_error("Limite precisa ser entre 1 e 1000000 ou ficar vazio.", field)
    return raw


def _billing_cycles(raw: list[str] | None) -> list[str] | None:
    if raw is None:
        return None
    allowed = {cycle.value for cycle in BillingCycle}
    normalized = []
    for cycle in raw:
        if cycle not in allowed:
            raise _payload_error("Ciclo de cobrança invalido.", "billing_cycles")
        normalized.append(cycle)
    return list(dict.fromkeys(normalized))


async def _allowed_plan_ids(bot: Any, guild_id: int, raw: list[str] | None) -> list[uuid.UUID] | None:
    if raw is None:
        return None
    plans = {str(plan.id): plan.id for plan in await bot.plan_service.list_plans(guild_id)}
    parsed: list[uuid.UUID] = []
    for plan_id in raw:
        if plan_id not in plans:
            raise _payload_error("Plano permitido invalido para este servidor.", "allowed_plan_ids")
        parsed.append(plans[plan_id])
    return list(dict.fromkeys(parsed))


def _security_notes() -> list[str]:
    return [
        "Fase 3.3: usa CouponService para criar, editar e ativar/desativar cupons.",
        "Nao altera registros financeiros, assinaturas, licencas, produtos ou cargos do Discord.",
        "Nao deleta cupom pelo painel; desativar preserva historico de uso.",
        "Tipo, valor, limites, datas, cargo e planos permitidos sao validados antes de salvar.",
    ]


async def _record_coupon_action(bot: Any, guild_id: int, action: str, coupon: DiscountCoupon) -> None:
    await bot.audit_log_service.record(
        guild_id=guild_id,
        category=AuditLogCategory.COUPON,
        action=action,
        executor_id=0,
        executor_name=_DASHBOARD_ACTOR,
        details={"cupom": coupon.code},
    )


async def _serialize_coupon(bot: Any, guild: discord.Guild, coupon: DiscountCoupon) -> MonetizationCouponManageRow:
    allowed_plan_ids = await bot.coupon_service.list_allowed_plans(coupon.id)
    return MonetizationCouponManageRow(
        id=str(coupon.id),
        code=coupon.code,
        description=coupon.description,
        emoji=coupon.emoji,
        discount_type=coupon.discount_type.value,
        discount_value=coupon.discount_value,
        discount_value_reais=_discount_value_reais(coupon),
        discount_label=_discount_label(coupon),
        active=coupon.active,
        starts_at=_iso(coupon.starts_at),
        expires_at=_iso(coupon.expires_at),
        max_global_uses=coupon.max_global_uses,
        max_uses_per_user=coupon.max_uses_per_user,
        required_role_id=str(coupon.required_role_id) if coupon.required_role_id else None,
        required_role_name=_role_name(guild, coupon.required_role_id),
        required_role_missing=coupon.required_role_id is not None and guild.get_role(coupon.required_role_id) is None,
        allow_stack=coupon.allow_stack,
        billing_cycles=list(coupon.billing_cycles or []),
        allowed_plan_ids=[str(plan_id) for plan_id in allowed_plan_ids],
        applies_to_all_plans=len(allowed_plan_ids) == 0,
        deleted=coupon.deleted_at is not None,
        created_at=_iso(coupon.created_at),
        updated_at=_iso(coupon.updated_at),
    )


async def _get_owned_coupon(bot: Any, guild_id: int, coupon_id: uuid.UUID) -> DiscountCoupon:
    coupon = await bot.coupon_service.get_coupon(coupon_id)
    if coupon is None or coupon.guild_id != guild_id or coupon.deleted_at is not None:
        raise HTTPException(status_code=404, detail={"error": {"code": "COUPON_NOT_FOUND", "message": "Cupom nao encontrado."}})
    return coupon


async def _mutation_fields(
    bot: Any,
    guild: discord.Guild,
    guild_id: int,
    payload: MonetizationCouponMutationRequest,
    *,
    existing: DiscountCoupon | None = None,
) -> tuple[dict[str, object], list[uuid.UUID] | None]:
    fields: dict[str, object] = {}
    if payload.code is not None:
        fields["code"] = normalize_code(_clean_text(payload.code, "code", required=True, max_len=_MAX_CODE) or "")
    if payload.description is not None:
        fields["description"] = _clean_text(payload.description, "description")
    if payload.emoji is not None:
        fields["emoji"] = _clean_text(payload.emoji, "emoji", max_len=64)

    future_type = _discount_type(payload.discount_type, existing.discount_type if existing else None)
    if payload.discount_type is not None:
        fields["discount_type"] = future_type
    if payload.discount_value is not None:
        fields["discount_value"] = _discount_value(payload.discount_value, future_type)
    elif existing is None:
        fields["discount_value"] = _discount_value("1", future_type)

    if payload.active is not None:
        fields["active"] = payload.active
    if payload.starts_at is not None:
        fields["starts_at"] = _parse_datetime(payload.starts_at, "starts_at")
    if payload.expires_at is not None:
        fields["expires_at"] = _parse_datetime(payload.expires_at, "expires_at")
    if payload.max_global_uses is not None:
        fields["max_global_uses"] = _limit(payload.max_global_uses, "max_global_uses")
    if payload.max_uses_per_user is not None:
        fields["max_uses_per_user"] = _limit(payload.max_uses_per_user, "max_uses_per_user")
    if payload.required_role_id is not None:
        fields["required_role_id"] = _role_id(guild, payload.required_role_id)
    if payload.allow_stack is not None:
        fields["allow_stack"] = payload.allow_stack
    cycles = _billing_cycles(payload.billing_cycles)
    if cycles is not None:
        fields["billing_cycles"] = cycles
    allowed = await _allowed_plan_ids(bot, guild_id, payload.allowed_plan_ids)

    starts_at = fields.get("starts_at", existing.starts_at if existing else None)
    expires_at = fields.get("expires_at", existing.expires_at if existing else None)
    if starts_at is not None and expires_at is not None and starts_at >= expires_at:
        raise _payload_error("A data de inicio precisa ser anterior a expiracao.", "starts_at")
    return fields, allowed


@router.get("/guild/{guild_id}/monetization/coupons/manage", response_model=MonetizationCouponListResponse)
async def list_manageable_coupons(request: Request, guild_id: int) -> MonetizationCouponListResponse:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    coupons = await bot.coupon_service.list_coupons(guild_id)
    return MonetizationCouponListResponse(
        guild_id=str(guild_id),
        items=[await _serialize_coupon(bot, guild, coupon) for coupon in coupons],
        security_notes=_security_notes(),
    )


@router.post("/guild/{guild_id}/monetization/coupons", response_model=MonetizationCouponMutationResponse)
async def create_coupon(request: Request, guild_id: int, payload: MonetizationCouponMutationRequest) -> MonetizationCouponMutationResponse:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    code = normalize_code(_clean_text(payload.code, "code", required=True, max_len=_MAX_CODE) or "")
    fields, allowed_plan_ids = await _mutation_fields(bot, guild, guild_id, payload)
    fields.pop("code", None)
    try:
        coupon = await bot.coupon_service.create_coupon(guild_id, code, **fields)
        if allowed_plan_ids is not None:
            await bot.coupon_service.set_allowed_plans(coupon.id, allowed_plan_ids)
            coupon = await _get_owned_coupon(bot, guild_id, coupon.id)
    except CouponError as exc:
        raise _payload_error(str(exc), "code") from exc
    await _record_coupon_action(bot, guild_id, "Cupom criado", coupon)
    return MonetizationCouponMutationResponse(
        item=await _serialize_coupon(bot, guild, coupon),
        security_notes=_security_notes(),
    )


@router.patch("/guild/{guild_id}/monetization/coupons/{coupon_id}", response_model=MonetizationCouponMutationResponse)
async def update_coupon(request: Request, guild_id: int, coupon_id: uuid.UUID, payload: MonetizationCouponMutationRequest) -> MonetizationCouponMutationResponse:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    existing = await _get_owned_coupon(bot, guild_id, coupon_id)
    fields, allowed_plan_ids = await _mutation_fields(bot, guild, guild_id, payload, existing=existing)
    try:
        coupon = await bot.coupon_service.update_coupon(coupon_id, **fields) if fields else existing
        if allowed_plan_ids is not None:
            await bot.coupon_service.set_allowed_plans(coupon_id, allowed_plan_ids)
            coupon = await _get_owned_coupon(bot, guild_id, coupon_id)
    except CouponError as exc:
        raise _payload_error(str(exc)) from exc
    await _record_coupon_action(bot, guild_id, "Cupom editado", coupon)
    return MonetizationCouponMutationResponse(
        item=await _serialize_coupon(bot, guild, coupon),
        security_notes=_security_notes(),
    )


@router.post("/guild/{guild_id}/monetization/coupons/{coupon_id}/toggle", response_model=MonetizationCouponMutationResponse)
async def toggle_coupon(request: Request, guild_id: int, coupon_id: uuid.UUID, payload: MonetizationCouponMutationRequest) -> MonetizationCouponMutationResponse:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    await _get_owned_coupon(bot, guild_id, coupon_id)
    if payload.active is None:
        raise _payload_error("Informe active.", "active")
    try:
        coupon = await bot.coupon_service.set_active(coupon_id, payload.active, executor=_DASHBOARD_EXECUTOR)
    except CouponError as exc:
        raise _payload_error(str(exc)) from exc
    return MonetizationCouponMutationResponse(
        item=await _serialize_coupon(bot, guild, coupon),
        security_notes=_security_notes(),
    )
