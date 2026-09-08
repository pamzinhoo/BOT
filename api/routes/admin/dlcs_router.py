from __future__ import annotations

import re
import uuid
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import discord
from fastapi import APIRouter, Depends, HTTPException, Request

from api.routes.admin.security import require_local_admin
from database.models.product import Product
from services.dlc_service import DlcError

router = APIRouter(
    prefix="/admin/api",
    tags=["admin-dlcs"],
    dependencies=[Depends(require_local_admin)],
)

_DASHBOARD_ACTOR = "Painel web"
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


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
        detail={"error": {"code": "INVALID_DLC", "message": message, "field": field}},
    )


def _clean_text(raw: Any, field: str, *, required: bool, max_len: int) -> str | None:
    value = str(raw or "").strip()
    if required and not value:
        raise _payload_error("Campo obrigatorio.", field)
    if len(value) > max_len:
        raise _payload_error(f"Use no maximo {max_len} caracteres.", field)
    return value or None


def _clean_slug(raw: Any) -> str:
    slug = str(raw or "").strip().lower()
    if not slug:
        raise _payload_error("Slug obrigatorio.", "slug")
    if len(slug) > 80:
        raise _payload_error("Use no maximo 80 caracteres no slug.", "slug")
    if not _SLUG_RE.match(slug):
        raise _payload_error("Use apenas letras minusculas, numeros e hifens no slug.", "slug")
    return slug


def _role_id(guild: discord.Guild, raw: Any, field: str) -> int:
    try:
        role_id = int(raw)
    except (TypeError, ValueError) as exc:
        raise _payload_error("Cargo invalido.", field) from exc
    role = guild.get_role(role_id)
    if role is None or role.is_default():
        raise _payload_error("Escolha um cargo existente e valido neste servidor.", field)
    return role_id


def _price_cents(payload: dict[str, Any]) -> int:
    if payload.get("price_amount") not in (None, ""):
        try:
            cents = int(payload.get("price_amount"))
        except (TypeError, ValueError) as exc:
            raise _payload_error("Preco invalido.", "price_amount") from exc
    else:
        raw = str(payload.get("price_reais") or "").strip().replace(",", ".")
        if not raw:
            raise _payload_error("Preco obrigatorio.", "price_reais")
        try:
            cents = int((Decimal(raw) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        except (InvalidOperation, ValueError) as exc:
            raise _payload_error("Preco invalido.", "price_reais") from exc
    if cents <= 0:
        raise _payload_error("Preco de DLC paga precisa ser maior que zero.", "price_reais")
    if cents > 1_000_000:
        raise _payload_error("Preco muito alto para o painel web.", "price_reais")
    return cents


def _money_label(cents: int | None, currency: str) -> str:
    if not cents:
        return "Gratis"
    return f"{currency} {cents / 100:.2f}".replace(".", ",")


async def _serialize_dlc(bot: Any, guild: discord.Guild, product: Product) -> dict[str, Any]:
    plan = await bot.dlc_service.get_purchase_plan(product.id)
    is_free = bot.dlc_service.is_free(product)
    role_id = product.required_role_id if is_free else (plan.role_id if plan is not None else None)
    role = guild.get_role(role_id) if role_id is not None else None
    guild_id = product.required_role_guild_id if is_free else (plan.guild_id if plan is not None else None)
    return {
        "id": str(product.id),
        "slug": product.slug,
        "name": product.name,
        "description": product.description,
        "kind": "free" if is_free else "paid",
        "is_active": bool(product.is_active),
        "deleted": product.deleted_at is not None,
        "price_amount": product.price_amount,
        "price_label": _money_label(product.price_amount, product.currency),
        "currency": product.currency,
        "position": product.position,
        "role_id": str(role_id) if role_id is not None else None,
        "role_name": role.name if role is not None else None,
        "role_missing": role_id is not None and role is None,
        "guild_id": str(guild_id) if guild_id is not None else None,
        "plan_id": str(plan.id) if plan is not None else None,
        "plan_active": bool(plan.is_active) if plan is not None else None,
        "created_at": product.created_at.isoformat() if product.created_at else None,
        "updated_at": product.updated_at.isoformat() if product.updated_at else None,
        "deleted_at": product.deleted_at.isoformat() if product.deleted_at else None,
    }


@router.get("/guild/{guild_id}/dlcs")
async def list_dlcs(request: Request, guild_id: int) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    dlcs = await bot.dlc_service.list_dlcs()
    return {
        "guild_id": str(guild_id),
        "items": [await _serialize_dlc(bot, guild, product) for product in dlcs],
    }


@router.post("/guild/{guild_id}/dlcs")
async def create_dlc(request: Request, guild_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    name = _clean_text(payload.get("name"), "name", required=True, max_len=150)
    slug = _clean_slug(payload.get("slug"))
    description = _clean_text(payload.get("description"), "description", required=False, max_len=1000)
    kind = str(payload.get("kind") or "free").lower()

    try:
        if kind == "free":
            product = await bot.dlc_service.create_free(
                guild_id=guild_id,
                name=name or slug,
                slug=slug,
                description=description,
                executor=_DASHBOARD_EXECUTOR,
            )
        elif kind == "paid":
            role_id = _role_id(guild, payload.get("role_id"), "role_id")
            price_amount = _price_cents(payload)
            product, _ = await bot.dlc_service.create_paid(
                guild_id=guild_id,
                name=name or slug,
                slug=slug,
                description=description,
                price_amount=price_amount,
                role_id=role_id,
                executor=_DASHBOARD_EXECUTOR,
            )
        else:
            raise _payload_error("Tipo de DLC invalido.", "kind")
    except DlcError as exc:
        raise _payload_error(str(exc)) from exc

    return {"item": await _serialize_dlc(bot, guild, product)}


@router.patch("/guild/{guild_id}/dlcs/{product_id}")
async def update_dlc(request: Request, guild_id: int, product_id: uuid.UUID, payload: dict[str, Any]) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    product = await bot.dlc_service.get(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "DLC_NOT_FOUND", "message": "DLC nao encontrada."}})

    try:
        if "name" in payload or "description" in payload:
            name = _clean_text(payload.get("name", product.name), "name", required=True, max_len=150) if "name" in payload else None
            description = _clean_text(payload.get("description"), "description", required=False, max_len=1000) if "description" in payload else None
            product = await bot.dlc_service.update_info(
                product_id,
                name=name,
                description=description,
                executor=_DASHBOARD_EXECUTOR,
            )
        if "price_amount" in payload or "price_reais" in payload:
            product = await bot.dlc_service.update_price(
                product_id,
                price_amount=_price_cents(payload),
                executor=_DASHBOARD_EXECUTOR,
            )
        if "role_id" in payload and payload.get("role_id") not in (None, ""):
            product = await bot.dlc_service.update_role(
                product_id,
                role_id=_role_id(guild, payload.get("role_id"), "role_id"),
                guild_id=guild_id,
                executor=_DASHBOARD_EXECUTOR,
            )
        if "is_active" in payload:
            if not isinstance(payload.get("is_active"), bool):
                raise _payload_error("Use verdadeiro ou falso.", "is_active")
            product = await bot.dlc_service.toggle_active(
                product_id,
                is_active=payload["is_active"],
                executor=_DASHBOARD_EXECUTOR,
            )
    except DlcError as exc:
        raise _payload_error(str(exc)) from exc

    return {"item": await _serialize_dlc(bot, guild, product)}


@router.post("/guild/{guild_id}/dlcs/{product_id}/disable")
async def disable_dlc(request: Request, guild_id: int, product_id: uuid.UUID) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    try:
        product = await bot.dlc_service.disable(product_id, executor=_DASHBOARD_EXECUTOR)
    except DlcError as exc:
        raise _payload_error(str(exc)) from exc
    if product is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "DLC_NOT_FOUND", "message": "DLC nao encontrada."}})
    return {"item": await _serialize_dlc(bot, guild, product)}
