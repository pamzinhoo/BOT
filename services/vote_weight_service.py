from __future__ import annotations

import uuid

import discord

from database.database import Database
from database.models.plan import Plan
from database.models.poll import VoteWeight
from database.repositories.vote_weight_repository import VoteWeightRepository
from utils.ttl_cache import TTLCache

_CACHE_TTL_SECONDS = 300.0


class VoteWeightService:
    """Peso de voto por cargo, por guild. Cacheado em memoria (invalidado em
    toda escrita) pra nao bater no banco a cada clique de voto — mesma ideia
    do cache ad-hoc de services/audit_log_service.py, generalizada em
    utils/ttl_cache.py."""

    def __init__(self, database: Database) -> None:
        self._database = database
        self._cache: TTLCache[int, list[VoteWeight]] = TTLCache(_CACHE_TTL_SECONDS)

    async def get_weights(self, guild_id: int) -> list[VoteWeight]:
        cached = self._cache.get(guild_id)
        if cached is not None:
            return cached
        async with self._database.session() as session:
            weights = await VoteWeightRepository(session).list_by_guild(guild_id)
        self._cache.set(guild_id, weights)
        return weights

    async def set_weight(
        self,
        guild_id: int,
        role_id: int,
        weight: int,
        *,
        source: str = "MANUAL",
        source_plan_id: uuid.UUID | None = None,
    ) -> VoteWeight:
        async with self._database.session() as session:
            repo = VoteWeightRepository(session)
            existing = await repo.get_by_guild_and_role(guild_id, role_id)
            if existing is not None:
                existing.weight = weight
                existing.source = source
                existing.source_plan_id = source_plan_id
                await session.flush()
                await session.refresh(existing)
                result = existing
            else:
                result = await repo.add(
                    VoteWeight(
                        guild_id=guild_id,
                        role_id=role_id,
                        weight=weight,
                        source=source,
                        source_plan_id=source_plan_id,
                    )
                )
        self._cache.invalidate(guild_id)
        return result

    async def delete_weight(self, guild_id: int, role_id: int) -> None:
        async with self._database.session() as session:
            repo = VoteWeightRepository(session)
            existing = await repo.get_by_guild_and_role(guild_id, role_id)
            if existing is not None:
                await repo.delete(existing)
        self._cache.invalidate(guild_id)

    async def remove_by_source_plan(self, plan_id: uuid.UUID) -> None:
        async with self._database.session() as session:
            repo = VoteWeightRepository(session)
            weights = await repo.list_by_source_plan(plan_id)
            guild_ids = {w.guild_id for w in weights}
            for weight in weights:
                await repo.delete(weight)
        for guild_id in guild_ids:
            self._cache.invalidate(guild_id)

    async def sync_plan_benefit_weight(self, guild_id: int, plan: Plan, weight: int) -> VoteWeight | None:
        """Vincula o peso de voto configurado num plano ao cargo que o plano
        entrega. plan_benefit.py fica intocado (e texto livre de vitrine) —
        esse e o vinculo estruturado, guardado direto em VoteWeight."""
        if plan.role_id is None:
            return None
        return await self.set_weight(
            guild_id, plan.role_id, weight, source="PLAN_BENEFIT", source_plan_id=plan.id
        )

    async def resolve_weight_for_member(self, guild_id: int, member: discord.Member) -> int:
        weights = await self.get_weights(guild_id)
        if not weights:
            return 1
        member_role_ids = {role.id for role in member.roles}
        matched = [w.weight for w in weights if w.role_id in member_role_ids]
        return max(matched) if matched else 1
