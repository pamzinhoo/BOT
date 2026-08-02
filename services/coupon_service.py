from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import discord

from core.logger import get_logger
from database.database import Database
from database.models.audit_log import AuditLogCategory
from database.models.discount_coupon import DiscountCoupon, DiscountType
from database.models.discount_coupon_redemption import DiscountCouponRedemption
from database.models.plan import Plan
from database.models.subscription import BillingCycle
from database.repositories.discount_coupon_repository import (
    DiscountCouponPlanRepository,
    DiscountCouponRedemptionRepository,
    DiscountCouponRepository,
)

if TYPE_CHECKING:
    from core.bot import LimerenceBot

logger = get_logger("coupon_service")

MAX_PERCENTAGE = 100


# --- excecoes (uma por motivo de recusa, pra UI mostrar mensagem precisa) ----


class CouponError(ValueError):
    """Base de toda recusa de cupom. A mensagem ja vem pronta pro usuario."""


class CouponNotFoundError(CouponError):
    pass


class CouponInactiveError(CouponError):
    pass


class CouponNotStartedError(CouponError):
    pass


class CouponExpiredError(CouponError):
    pass


class CouponGlobalLimitReachedError(CouponError):
    pass


class CouponUserLimitReachedError(CouponError):
    pass


class CouponPlanNotAllowedError(CouponError):
    pass


class CouponCycleNotAllowedError(CouponError):
    pass


class CouponRoleRequiredError(CouponError):
    pass


class DuplicateCouponCodeError(CouponError):
    pass


class InvalidCouponValueError(CouponError):
    pass


@dataclass(frozen=True)
class CouponApplication:
    """Resultado de uma validacao bem-sucedida. `final_amount` ja vem clampado
    em 0 — desconto maior que o preco nunca gera valor negativo nem erro.

    Hoje so existe UM cupom por compra (`allow_stack` fica guardado no cupom
    mas ainda nao e consumido). Se um dia houver acumulo, a extensao natural e
    um `validate_and_price_many(codes: list[str])` que dobre sobre esta mesma
    funcao acumulando `discount_amount` e devolva uma lista de
    CouponApplication — nada aqui assume "no maximo um cupom" de forma que
    exija mudanca quebrando assinatura."""

    coupon: DiscountCoupon
    original_amount: int
    discount_amount: int
    final_amount: int


@dataclass(frozen=True)
class CouponStats:
    coupon: DiscountCoupon
    total_redemptions: int
    max_global_uses: int | None
    revenue_cents: int
    discounted_cents: int
    last_used_at: datetime | None


def normalize_code(code: str) -> str:
    """Codigos sao guardados e comparados SEMPRE em maiusculas, sem espacos nas
    bordas. E o que torna a comparacao case-insensitive sem indice funcional."""
    return code.strip().upper()


def format_discount(coupon: DiscountCoupon, *, currency: str = "BRL") -> str:
    if coupon.discount_type == DiscountType.PERCENTAGE:
        return f"{coupon.discount_value}%"
    return f"{currency} {coupon.discount_value / 100:.2f}"


def compute_discount(coupon: DiscountCoupon, original_amount: int) -> tuple[int, int]:
    """(desconto, valor_final). Toda a matematica de cupom do projeto vive
    AQUI — nenhuma View/Cog recalcula preco."""
    if coupon.discount_type == DiscountType.PERCENTAGE:
        discount = round(original_amount * coupon.discount_value / 100)
    else:
        discount = coupon.discount_value
    discount = max(0, min(discount, original_amount))
    return discount, max(0, original_amount - discount)


class CouponService:
    """Fonte unica de verdade dos cupons de desconto: CRUD, validacao e
    matematica. Cogs/Views nunca calculam desconto nem checam limite — so
    chamam este servico."""

    def __init__(self, database: Database, bot: "LimerenceBot | None" = None) -> None:
        self._database = database
        self._bot = bot

    # --- CRUD ---------------------------------------------------------------

    async def list_coupons(self, guild_id: int, *, only_active: bool = False) -> list[DiscountCoupon]:
        async with self._database.session() as session:
            return await DiscountCouponRepository(session).list_by_guild(
                guild_id, only_active=only_active
            )

    async def get_coupon(self, coupon_id: uuid.UUID) -> DiscountCoupon | None:
        async with self._database.session() as session:
            return await DiscountCouponRepository(session).get_by_id(coupon_id)

    async def get_by_code(self, guild_id: int, code: str) -> DiscountCoupon | None:
        """Sempre com guild_id — nao existe caminho pra resolver um cupom sem
        dizer de qual servidor ele e."""
        async with self._database.session() as session:
            return await DiscountCouponRepository(session).get_by_code(
                guild_id, normalize_code(code)
            )

    async def create_coupon(self, guild_id: int, code: str, **fields: object) -> DiscountCoupon:
        normalized = normalize_code(code)
        if not normalized:
            raise InvalidCouponValueError("O código do cupom não pode ficar vazio.")
        async with self._database.session() as session:
            repo = DiscountCouponRepository(session)
            existing = await repo.get_by_code(guild_id, normalized, include_deleted=True)
            if existing is not None:
                raise DuplicateCouponCodeError(
                    f"Já existe um cupom com o código `{normalized}` neste servidor."
                )
            coupon = DiscountCoupon(
                guild_id=guild_id,
                code=normalized,
                billing_cycles=[],
                discount_type=DiscountType.PERCENTAGE,
                discount_value=0,
            )
            for key, value in fields.items():
                setattr(coupon, key, value)
            self._validate_value(coupon.discount_type, coupon.discount_value, allow_zero=True)
            return await repo.add(coupon)

    async def update_coupon(self, coupon_id: uuid.UUID, **fields: object) -> DiscountCoupon:
        async with self._database.session() as session:
            repo = DiscountCouponRepository(session)
            coupon = await repo.get_by_id(coupon_id)
            if coupon is None:
                raise CouponNotFoundError("Cupom não encontrado.")
            if "code" in fields:
                normalized = normalize_code(str(fields["code"]))
                if not normalized:
                    raise InvalidCouponValueError("O código do cupom não pode ficar vazio.")
                clash = await repo.get_by_code(coupon.guild_id, normalized, include_deleted=True)
                if clash is not None and clash.id != coupon.id:
                    raise DuplicateCouponCodeError(
                        f"Já existe um cupom com o código `{normalized}` neste servidor."
                    )
                fields["code"] = normalized
            for key, value in fields.items():
                setattr(coupon, key, value)
            self._validate_value(coupon.discount_type, coupon.discount_value, allow_zero=True)
            await session.flush()
            await session.refresh(coupon)
            return coupon

    async def set_discount(
        self, coupon_id: uuid.UUID, discount_type: DiscountType, discount_value: int
    ) -> DiscountCoupon:
        """Unico caminho pra mexer em tipo+valor juntos — valida > 0 aqui,
        nunca na View."""
        self._validate_value(discount_type, discount_value, allow_zero=False)
        return await self.update_coupon(
            coupon_id, discount_type=discount_type, discount_value=discount_value
        )

    @staticmethod
    def _validate_value(
        discount_type: DiscountType, discount_value: int, *, allow_zero: bool
    ) -> None:
        if discount_value < 0:
            raise InvalidCouponValueError("O valor do desconto não pode ser negativo.")
        if discount_value == 0:
            if allow_zero:
                return  # cupom recem-criado ainda sem valor configurado
            raise InvalidCouponValueError("O valor do desconto precisa ser maior que zero.")
        if discount_type == DiscountType.PERCENTAGE and discount_value > MAX_PERCENTAGE:
            raise InvalidCouponValueError("A porcentagem precisa estar entre 1 e 100.")

    async def set_active(
        self,
        coupon_id: uuid.UUID,
        active: bool,
        *,
        executor: discord.Member | discord.User | None = None,
    ) -> DiscountCoupon:
        coupon = await self.update_coupon(coupon_id, active=active)
        await self._audit(
            coupon,
            action="Cupom ativado" if active else "Cupom desativado",
            executor_id=executor.id if executor else None,
            executor_name=str(executor) if executor else None,
        )
        return coupon

    async def duplicate_coupon(
        self,
        coupon_id: uuid.UUID,
        *,
        new_code: str | None = None,
        executor: discord.Member | discord.User | None = None,
    ) -> DiscountCoupon:
        """Clona todos os campos + os planos permitidos. Sem `new_code`, gera
        `<CODIGO>-COPIA`, `-COPIA-2`, ... ate achar um livre."""
        async with self._database.session() as session:
            repo = DiscountCouponRepository(session)
            plan_repo = DiscountCouponPlanRepository(session)
            source = await repo.get_by_id(coupon_id)
            if source is None:
                raise CouponNotFoundError("Cupom não encontrado.")

            if new_code is not None:
                code = normalize_code(new_code)
                if await repo.get_by_code(source.guild_id, code, include_deleted=True) is not None:
                    raise DuplicateCouponCodeError(
                        f"Já existe um cupom com o código `{code}` neste servidor."
                    )
            else:
                base = f"{source.code}-COPIA"
                code = base
                suffix = 2
                while (
                    await repo.get_by_code(source.guild_id, code, include_deleted=True) is not None
                ):
                    code = f"{base}-{suffix}"
                    suffix += 1

            clone = await repo.add(
                DiscountCoupon(
                    guild_id=source.guild_id,
                    code=code,
                    description=source.description,
                    emoji=source.emoji,
                    discount_type=source.discount_type,
                    discount_value=source.discount_value,
                    active=source.active,
                    starts_at=source.starts_at,
                    expires_at=source.expires_at,
                    max_global_uses=source.max_global_uses,
                    max_uses_per_user=source.max_uses_per_user,
                    required_role_id=source.required_role_id,
                    allow_stack=source.allow_stack,
                    billing_cycles=list(source.billing_cycles or []),
                )
            )
            plan_ids = await plan_repo.list_plan_ids(source.id)
            if plan_ids:
                await plan_repo.replace_for_coupon(clone.id, plan_ids)
        await self._audit(
            clone,
            action="Cupom criado",
            details={"duplicado_de": source.code},
            executor_id=executor.id if executor else None,
            executor_name=str(executor) if executor else None,
        )
        return clone

    async def delete_coupon(
        self,
        coupon_id: uuid.UUID,
        *,
        executor: discord.Member | discord.User | None = None,
    ) -> bool:
        """Devolve True se a linha foi apagada de verdade, False se virou
        soft-delete.

        Regra (spec "Nunca apagar histórico"): cupom SEM resgates pode sumir
        fisicamente; cupom COM resgates vira soft-delete (active=False +
        deleted_at) porque a FK RESTRICT em discount_coupon_redemptions existe
        justamente pra impedir que o historico de uso seja levado junto. Em
        ambos os casos o cupom some das listagens e para de validar."""
        async with self._database.session() as session:
            repo = DiscountCouponRepository(session)
            redemptions = DiscountCouponRedemptionRepository(session)
            coupon = await repo.get_by_id(coupon_id)
            if coupon is None:
                return False
            snapshot = (coupon.guild_id, coupon.code)
            used = await redemptions.count_for_coupon(coupon_id)
            if used == 0:
                await DiscountCouponPlanRepository(session).replace_for_coupon(coupon_id, [])
                await repo.delete(coupon)
                hard = True
            else:
                coupon.active = False
                coupon.deleted_at = datetime.now(UTC)
                await session.flush()
                hard = False
        await self._audit_raw(
            guild_id=snapshot[0],
            action="Cupom removido",
            details={"cupom": snapshot[1], "modo": "definitivo" if hard else "arquivado"},
            executor_id=executor.id if executor else None,
            executor_name=str(executor) if executor else None,
        )
        return hard

    # --- planos permitidos --------------------------------------------------

    async def list_allowed_plans(self, coupon_id: uuid.UUID) -> list[uuid.UUID]:
        """Lista VAZIA = cupom vale pra TODOS os planos (ver
        DiscountCouponPlan)."""
        async with self._database.session() as session:
            return await DiscountCouponPlanRepository(session).list_plan_ids(coupon_id)

    async def set_allowed_plans(self, coupon_id: uuid.UUID, plan_ids: list[uuid.UUID]) -> None:
        """Substitui a lista inteira (mesmo padrao de PlanService.set_benefits).
        Passar lista vazia libera o cupom pra todos os planos."""
        async with self._database.session() as session:
            await DiscountCouponPlanRepository(session).replace_for_coupon(coupon_id, plan_ids)

    # --- validacao ----------------------------------------------------------

    async def validate_and_price(
        self,
        guild_id: int,
        code: str,
        member: discord.Member | None,
        plan: Plan,
        billing_cycle: BillingCycle,
        original_amount: int,
    ) -> CouponApplication:
        """Valida TUDO (existencia/escopo de guild, ativo, janela de validade,
        limite global, limite por usuario, plano, ciclo e cargo obrigatorio) e
        devolve o preco ja com desconto. Levanta uma CouponError especifica no
        primeiro motivo de recusa.

        Expiracao e checada de forma preguicosa AQUI (nao ha scheduler de
        cupom, ao contrario da renovacao de assinatura): na primeira tentativa
        de uso apos `expires_at`, o cupom e desativado e um evento "Cupom
        expirado" e auditado uma unica vez."""
        normalized = normalize_code(code)
        now = datetime.now(UTC)

        async with self._database.session() as session:
            repo = DiscountCouponRepository(session)
            coupon = await repo.get_by_code(guild_id, normalized)
            if coupon is None:
                raise CouponNotFoundError(f"Cupom `{normalized}` não encontrado neste servidor.")

            expired = coupon.expires_at is not None and _as_utc(coupon.expires_at) < now
            just_expired = expired and coupon.active
            if just_expired:
                coupon.active = False
                await session.flush()

            allowed_plan_ids = await DiscountCouponPlanRepository(session).list_plan_ids(coupon.id)
            redemptions = DiscountCouponRedemptionRepository(session)
            global_uses = await redemptions.count_for_coupon(coupon.id)
            user_uses = (
                await redemptions.count_for_coupon_and_user(coupon.id, member.id)
                if member is not None
                else 0
            )

        if just_expired:
            await self._audit(coupon, action="Cupom expirado")
        if expired:
            raise CouponExpiredError(f"O cupom `{coupon.code}` está expirado.")
        if not coupon.active:
            raise CouponInactiveError(f"O cupom `{coupon.code}` está inativo.")
        if coupon.starts_at is not None and _as_utc(coupon.starts_at) > now:
            raise CouponNotStartedError(
                f"O cupom `{coupon.code}` só passa a valer em "
                f"{_as_utc(coupon.starts_at).strftime('%d/%m/%Y')}."
            )
        if coupon.max_global_uses is not None and global_uses >= coupon.max_global_uses:
            raise CouponGlobalLimitReachedError(
                f"O cupom `{coupon.code}` atingiu o limite de utilizações."
            )
        if coupon.max_uses_per_user is not None and user_uses >= coupon.max_uses_per_user:
            raise CouponUserLimitReachedError(
                f"Você já usou o cupom `{coupon.code}` o número máximo de vezes."
            )
        if allowed_plan_ids and plan.id not in allowed_plan_ids:
            raise CouponPlanNotAllowedError(
                f"O cupom `{coupon.code}` não é válido para o plano **{plan.name}**."
            )
        cycles = list(coupon.billing_cycles or [])
        if cycles and billing_cycle.value not in cycles:
            raise CouponCycleNotAllowedError(
                f"O cupom `{coupon.code}` não é válido para essa forma de cobrança."
            )
        if coupon.required_role_id is not None:
            if member is None or coupon.required_role_id not in {r.id for r in member.roles}:
                raise CouponRoleRequiredError(
                    f"O cupom `{coupon.code}` é exclusivo para quem tem "
                    f"<@&{coupon.required_role_id}>."
                )

        discount, final = compute_discount(coupon, original_amount)
        return CouponApplication(
            coupon=coupon,
            original_amount=original_amount,
            discount_amount=discount,
            final_amount=final,
        )

    # --- resgate ------------------------------------------------------------

    async def record_redemption(
        self,
        coupon_id: uuid.UUID,
        guild_id: int,
        user_id: int,
        payment_id: uuid.UUID | None,
        original_price: int,
        discount_amount: int,
        final_price: int,
    ) -> DiscountCouponRedemption:
        async with self._database.session() as session:
            # trava a linha do cupom antes de reconferir os limites — fecha a
            # corrida entre validate_and_price (so uma pre-checagem, sem lock)
            # e o insert: duas compras concorrentes nao conseguem mais passar
            # ambas do limite configurado, uma delas sempre falha aqui.
            coupon = await DiscountCouponRepository(session).get_by_id_locked(coupon_id)
            redemptions = DiscountCouponRedemptionRepository(session)
            if coupon is not None:
                global_uses = await redemptions.count_for_coupon(coupon_id)
                if coupon.max_global_uses is not None and global_uses >= coupon.max_global_uses:
                    raise CouponGlobalLimitReachedError(
                        f"O cupom `{coupon.code}` atingiu o limite de utilizações."
                    )
                user_uses = await redemptions.count_for_coupon_and_user(coupon_id, user_id)
                if coupon.max_uses_per_user is not None and user_uses >= coupon.max_uses_per_user:
                    raise CouponUserLimitReachedError(
                        f"Você já usou o cupom `{coupon.code}` o número máximo de vezes."
                    )
            redemption = await redemptions.add(
                DiscountCouponRedemption(
                    coupon_id=coupon_id,
                    guild_id=guild_id,
                    user_id=user_id,
                    payment_id=payment_id,
                    original_price=original_price,
                    discount_amount=discount_amount,
                    final_price=final_price,
                )
            )
            total = await redemptions.count_for_coupon(coupon_id)

        if coupon is not None:
            await self._audit(
                coupon,
                action="Cupom utilizado",
                target_id=user_id,
                details={
                    "cupom": coupon.code,
                    "preco_original": original_price,
                    "desconto": discount_amount,
                    "preco_final": final_price,
                },
            )
            # "atingiu limite" e disparado no instante EXATO em que o limite e
            # alcancado (comparacao apos o insert), nunca de novo depois.
            if coupon.max_global_uses is not None and total == coupon.max_global_uses:
                await self._audit(
                    coupon,
                    action="Cupom atingiu limite",
                    details={"cupom": coupon.code, "limite": coupon.max_global_uses},
                )
        return redemption

    # --- estatisticas -------------------------------------------------------

    async def coupon_stats(self, coupon_id: uuid.UUID) -> CouponStats | None:
        async with self._database.session() as session:
            coupon = await DiscountCouponRepository(session).get_by_id(coupon_id)
            if coupon is None:
                return None
            total, revenue, discounted, last_used = await DiscountCouponRedemptionRepository(
                session
            ).totals_for_coupon(coupon_id)
        return CouponStats(
            coupon=coupon,
            total_redemptions=total,
            max_global_uses=coupon.max_global_uses,
            revenue_cents=revenue,
            discounted_cents=discounted,
            last_used_at=last_used,
        )

    async def remaining_uses(self, coupon_id: uuid.UUID) -> int | None:
        """None = ilimitado (∞)."""
        async with self._database.session() as session:
            coupon = await DiscountCouponRepository(session).get_by_id(coupon_id)
            if coupon is None or coupon.max_global_uses is None:
                return None
            used = await DiscountCouponRedemptionRepository(session).count_for_coupon(coupon_id)
        return max(0, coupon.max_global_uses - used)

    # --- auditoria ----------------------------------------------------------

    async def _audit(
        self,
        coupon: DiscountCoupon,
        *,
        action: str,
        executor_id: int | None = None,
        executor_name: str | None = None,
        target_id: int | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        await self._audit_raw(
            guild_id=coupon.guild_id,
            action=action,
            executor_id=executor_id,
            executor_name=executor_name,
            target_id=target_id,
            details=details or {"cupom": coupon.code},
        )

    async def _audit_raw(
        self,
        *,
        guild_id: int,
        action: str,
        executor_id: int | None = None,
        executor_name: str | None = None,
        target_id: int | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        """Acoplamento opcional com o bot (igual _notify_renewed em
        SubscriptionService): sem bot montado (testes), o fluxo segue igual."""
        if self._bot is None:
            return
        try:
            await self._bot.audit_log_service.record(
                guild_id=guild_id,
                category=AuditLogCategory.COUPON,
                action=action,
                executor_id=executor_id,
                executor_name=executor_name,
                target_id=target_id,
                details=details or {},
            )
        except Exception:
            logger.exception("Falha ao auditar evento de cupom '%s' na guild %s.", action, guild_id)


def _as_utc(value: datetime) -> datetime:
    """Colunas timezone-aware podem voltar naive dependendo do driver/teste."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
