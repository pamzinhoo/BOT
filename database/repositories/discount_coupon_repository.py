from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, func, select

from database.models.discount_coupon import DiscountCoupon
from database.models.discount_coupon_plan import DiscountCouponPlan
from database.models.discount_coupon_redemption import DiscountCouponRedemption
from database.repositories.base_repository import BaseRepository


class DiscountCouponRepository(BaseRepository[DiscountCoupon]):
    """Todas as consultas sao obrigatoriamente filtradas por guild_id — um
    cupom de uma guild nunca pode ser alcancado a partir de outra."""

    model = DiscountCoupon

    async def get_by_id(self, id_: uuid.UUID) -> DiscountCoupon | None:
        return await self.session.get(DiscountCoupon, id_)

    async def get_by_id_locked(self, id_: uuid.UUID) -> DiscountCoupon | None:
        """Mesmo que get_by_id, mas com SELECT ... FOR UPDATE — trava a linha
        do cupom ate o fim da transacao, pra que duas resgates concorrentes
        nao consigam ambos passar da checagem de limite antes de qualquer
        um gravar sua redemption (senao o limite configurado e ultrapassado)."""
        stmt = select(DiscountCoupon).where(DiscountCoupon.id == id_).with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_code(
        self, guild_id: int, code: str, *, include_deleted: bool = False
    ) -> DiscountCoupon | None:
        """`code` ja tem que chegar normalizado (maiusculo) — quem normaliza e
        o CouponService. A comparacao ainda usa upper() no lado do banco pra
        tolerar linhas antigas gravadas fora do padrao."""
        stmt = select(DiscountCoupon).where(
            DiscountCoupon.guild_id == guild_id,
            func.upper(DiscountCoupon.code) == code.upper(),
        )
        if not include_deleted:
            stmt = stmt.where(DiscountCoupon.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_guild(
        self, guild_id: int, *, only_active: bool = False, include_deleted: bool = False
    ) -> list[DiscountCoupon]:
        stmt = select(DiscountCoupon).where(DiscountCoupon.guild_id == guild_id)
        if only_active:
            stmt = stmt.where(DiscountCoupon.active.is_(True))
        if not include_deleted:
            stmt = stmt.where(DiscountCoupon.deleted_at.is_(None))
        stmt = stmt.order_by(DiscountCoupon.created_at.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class DiscountCouponPlanRepository(BaseRepository[DiscountCouponPlan]):
    model = DiscountCouponPlan

    async def list_by_coupon(self, coupon_id: uuid.UUID) -> list[DiscountCouponPlan]:
        result = await self.session.execute(
            select(DiscountCouponPlan).where(DiscountCouponPlan.coupon_id == coupon_id)
        )
        return list(result.scalars().all())

    async def list_plan_ids(self, coupon_id: uuid.UUID) -> list[uuid.UUID]:
        result = await self.session.execute(
            select(DiscountCouponPlan.plan_id).where(DiscountCouponPlan.coupon_id == coupon_id)
        )
        return list(result.scalars().all())

    async def replace_for_coupon(self, coupon_id: uuid.UUID, plan_ids: list[uuid.UUID]) -> None:
        """Substitui a lista inteira de planos permitidos do cupom, dentro da
        transacao corrente (atomico com o delete: se o flush falhar, o delete
        acima tambem e revertido pelo `async with session()` do chamador).

        `SELECT ... FOR UPDATE` na linha do cupom antes do delete/insert serializa
        duas chamadas concorrentes pro MESMO coupon_id (ex.: dois admins salvando
        o mesmo formulario ao mesmo tempo) — a segunda chamada espera a primeira
        commitar em vez de correr pro mesmo unique constraint
        (uq_discount_coupon_plan) e estourar IntegrityError."""
        await self.session.execute(
            select(DiscountCoupon.id).where(DiscountCoupon.id == coupon_id).with_for_update()
        )
        await self.session.execute(
            delete(DiscountCouponPlan).where(DiscountCouponPlan.coupon_id == coupon_id)
        )
        for plan_id in dict.fromkeys(plan_ids):
            self.session.add(DiscountCouponPlan(coupon_id=coupon_id, plan_id=plan_id))
        await self.session.flush()


class DiscountCouponRedemptionRepository(BaseRepository[DiscountCouponRedemption]):
    model = DiscountCouponRedemption

    async def count_for_coupon(self, coupon_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(DiscountCouponRedemption)
            .where(DiscountCouponRedemption.coupon_id == coupon_id)
        )
        return int(result.scalar_one())

    async def count_for_coupon_and_user(self, coupon_id: uuid.UUID, user_id: int) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(DiscountCouponRedemption)
            .where(
                DiscountCouponRedemption.coupon_id == coupon_id,
                DiscountCouponRedemption.user_id == user_id,
            )
        )
        return int(result.scalar_one())

    async def totals_for_coupon(self, coupon_id: uuid.UUID) -> tuple[int, int, int, datetime | None]:
        """(total_resgates, receita_gerada, total_descontado, ultima_utilizacao)."""
        result = await self.session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(DiscountCouponRedemption.final_price), 0),
                func.coalesce(func.sum(DiscountCouponRedemption.discount_amount), 0),
                func.max(DiscountCouponRedemption.redeemed_at),
            ).where(DiscountCouponRedemption.coupon_id == coupon_id)
        )
        total, revenue, discounted, last_used = result.one()
        return int(total), int(revenue), int(discounted), last_used

    async def list_by_coupon(
        self, coupon_id: uuid.UUID, *, limit: int = 50
    ) -> list[DiscountCouponRedemption]:
        result = await self.session.execute(
            select(DiscountCouponRedemption)
            .where(DiscountCouponRedemption.coupon_id == coupon_id)
            .order_by(DiscountCouponRedemption.redeemed_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
