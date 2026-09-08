from __future__ import annotations

import contextlib
import re
import uuid
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import discord
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from api.routes.admin.security import require_local_admin
from database.models.license import License, LicenseStatus
from database.models.player import Player
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


def _member_name(guild: discord.Guild, discord_id: int) -> str | None:
    member = guild.get_member(discord_id)
    return member.display_name if member is not None else None


def _free_dlc_embed(product: Product) -> discord.Embed:
    embed = discord.Embed(
        title="🎁 Nova DLC Grátis!",
        description=(f"**{product.name}** já está disponível!\n" + (product.description or "")).strip(),
        color=discord.Color.green(),
    )
    embed.set_footer(
        text="Tem o cargo Verificado? Já pode jogar. Ainda não vinculou sua conta? "
        "Entre no jogo e conecte seu Discord."
    )
    return embed


async def _free_dlc_announcement_channel(bot: Any, guild_id: int) -> Any | None:
    settings = await bot.subscription_service.get_settings(guild_id)
    channel_id = settings.dlc_announcement_channel_id
    if channel_id is None:
        return None
    channel = bot.get_channel(channel_id)
    if not isinstance(channel, discord.abc.Messageable):
        return None
    return channel


def _message_text(message: Any) -> str:
    parts = [getattr(message, "content", "") or ""]
    for embed in getattr(message, "embeds", []):
        parts.extend([embed.title or "", embed.description or ""])
    return "\n".join(parts).casefold()


async def _matching_free_dlc_messages(
    bot: Any,
    guild_id: int,
    product: Product,
    *,
    match_terms: set[str] | None = None,
) -> list[Any]:
    if product.price_amount:
        return []
    channel = await _free_dlc_announcement_channel(bot, guild_id)
    history = getattr(channel, "history", None)
    if history is None:
        return []
    bot_user_id = getattr(getattr(bot, "user", None), "id", None)
    terms = {product.name.casefold(), product.slug.casefold(), *(match_terms or set())}
    matches: list[Any] = []
    async for message in history(limit=100):
        if bot_user_id is not None and message.author.id != bot_user_id:
            continue
        haystack = _message_text(message)
        if any(term and term in haystack for term in terms):
            matches.append(message)
    return matches


async def _delete_free_dlc_announcements(
    bot: Any,
    guild_id: int,
    product: Product,
    *,
    match_terms: set[str] | None = None,
) -> None:
    """Remove anuncios soltos de DLC gratuita quando ela sai do catalogo."""
    try:
        for message in await _matching_free_dlc_messages(bot, guild_id, product, match_terms=match_terms):
            with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                await message.delete()
    except Exception:
        # Limpeza de anuncio nao pode impedir a remocao/desativacao da DLC.
        return


async def _sync_free_dlc_announcement(
    bot: Any,
    guild_id: int,
    product: Product,
    *,
    match_terms: set[str] | None = None,
) -> None:
    """Mantem o anuncio de DLC gratis em sincronia com o cadastro.

    Se achar a mensagem antiga, edita a propria mensagem. Se houver duplicadas
    antigas, edita a primeira e apaga as extras. Se o anuncio for antigo demais
    para aparecer nas ultimas 100 mensagens, posta um novo.
    """
    if product.price_amount or product.deleted_at is not None or not product.is_active:
        return
    try:
        channel = await _free_dlc_announcement_channel(bot, guild_id)
        if channel is None:
            return
        embed = _free_dlc_embed(product)
        messages = await _matching_free_dlc_messages(bot, guild_id, product, match_terms=match_terms)
        if messages:
            first, *duplicates = messages
            with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                await first.edit(
                    content="@everyone",
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(everyone=False),
                )
            for message in duplicates:
                with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                    await message.delete()
            return
        await channel.send(
            content="@everyone",
            embed=embed,
            allowed_mentions=discord.AllowedMentions(everyone=True),
        )
    except Exception:
        # Atualizar anuncio nao pode quebrar a edicao da DLC.
        return


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


@router.get("/guild/{guild_id}/dlcs/{product_id}/access")
async def dlc_access(request: Request, guild_id: int, product_id: uuid.UUID) -> dict[str, Any]:
    """Lista somente leitura de quem tem acesso/registro na DLC.

    Varredura de seguranca:
    - nao altera License, Player, Plan, Product nem cargos;
    - nao retorna dados internos sensiveis;
    - nomes do Discord aparecem so quando o membro esta no cache da guild;
    - inclui titulares por License e usuarios que possuem o cargo vinculado.
    """
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    product = await bot.dlc_service.get(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "DLC_NOT_FOUND", "message": "DLC nao encontrada."}})

    plan = await bot.dlc_service.get_purchase_plan(product.id)
    is_free = bot.dlc_service.is_free(product)
    role_id = product.required_role_id if is_free else (plan.role_id if plan is not None else None)
    role = guild.get_role(role_id) if role_id is not None else None

    access_by_discord_id: dict[int, dict[str, Any]] = {}
    async with bot.database.session() as session:
        rows = (
            await session.execute(
                select(License, Player)
                .join(Player, Player.id == License.player_id)
                .where(License.product_id == product_id)
                .order_by(License.activated_at.desc().nullslast(), License.created_at.desc())
                .limit(200)
            )
        ).all()

    for license_row, player in rows:
        discord_id = int(player.discord_id)
        access_by_discord_id[discord_id] = {
            "discord_id": str(discord_id),
            "discord_name": _member_name(guild, discord_id) or player.discord_username,
            "player_id": str(player.id),
            "source": license_row.purchase_source,
            "status": license_row.status.value,
            "active": license_row.status == LicenseStatus.ACTIVE,
            "has_role_now": False,
            "activated_at": license_row.activated_at.isoformat() if license_row.activated_at else None,
            "expires_at": license_row.expires_at.isoformat() if license_row.expires_at else None,
            "revoked_at": license_row.revoked_at.isoformat() if license_row.revoked_at else None,
        }

    if role is not None:
        for member in role.members:
            current = access_by_discord_id.setdefault(
                int(member.id),
                {
                    "discord_id": str(member.id),
                    "discord_name": member.display_name,
                    "player_id": None,
                    "source": "discord_role",
                    "status": "role_only",
                    "active": True,
                    "has_role_now": True,
                    "activated_at": None,
                    "expires_at": None,
                    "revoked_at": None,
                },
            )
            current["has_role_now"] = True
            current["discord_name"] = member.display_name
            if current["status"] != LicenseStatus.ACTIVE.value and current["source"] != "discord_role":
                current["source"] = f"{current['source']} + discord_role"

    holders = sorted(
        access_by_discord_id.values(),
        key=lambda item: (not item["active"], str(item.get("discord_name") or item["discord_id"]).casefold()),
    )
    return {
        "guild_id": str(guild_id),
        "product": await _serialize_dlc(bot, guild, product),
        "role_id": str(role_id) if role_id is not None else None,
        "role_name": role.name if role is not None else None,
        "role_missing": role_id is not None and role is None,
        "total": len(holders),
        "items": holders,
        "security_notes": [
            "Somente leitura: nao altera licencas, cargos, produtos, planos ou pagamentos.",
            "Nao retorna dados internos de License nem informacoes sensiveis do Player.",
            "Nome do Discord so aparece quando o bot consegue resolver pelo cache da guild ou pelo username salvo no Player.",
        ],
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
    is_free = bot.dlc_service.is_free(product)
    text_changed = "name" in payload or "description" in payload
    old_match_terms = {product.name.casefold(), product.slug.casefold()} if is_free else set()

    try:
        if text_changed:
            name = _clean_text(payload.get("name", product.name), "name", required=True, max_len=150) if "name" in payload else None
            description = _clean_text(payload.get("description"), "description", required=False, max_len=1000) if "description" in payload else None
            product = await bot.dlc_service.update_info(
                product_id,
                name=name,
                description=description,
                executor=_DASHBOARD_EXECUTOR,
            )
        if ("price_amount" in payload or "price_reais" in payload) and not is_free:
            product = await bot.dlc_service.update_price(
                product_id,
                price_amount=_price_cents(payload),
                executor=_DASHBOARD_EXECUTOR,
            )
        if "role_id" in payload and payload.get("role_id") not in (None, "") and not is_free:
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
            if payload["is_active"]:
                await _sync_free_dlc_announcement(bot, guild_id, product, match_terms=old_match_terms)
            else:
                await _delete_free_dlc_announcements(bot, guild_id, product, match_terms=old_match_terms)
        elif text_changed and is_free and product.is_active:
            await _sync_free_dlc_announcement(bot, guild_id, product, match_terms=old_match_terms)
    except DlcError as exc:
        raise _payload_error(str(exc)) from exc

    return {"item": await _serialize_dlc(bot, guild, product)}


@router.post("/guild/{guild_id}/dlcs/{product_id}/disable")
async def disable_dlc(request: Request, guild_id: int, product_id: uuid.UUID) -> dict[str, Any]:
    bot = _bot(request)
    guild = _guild(bot, guild_id)
    product = await bot.dlc_service.get(product_id)
    old_match_terms = {product.name.casefold(), product.slug.casefold()} if product is not None else set()
    try:
        product = await bot.dlc_service.disable(product_id, executor=_DASHBOARD_EXECUTOR)
    except DlcError as exc:
        raise _payload_error(str(exc)) from exc
    if product is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "DLC_NOT_FOUND", "message": "DLC nao encontrada."}})
    await _delete_free_dlc_announcements(bot, guild_id, product, match_terms=old_match_terms)
    return {"item": await _serialize_dlc(bot, guild, product)}