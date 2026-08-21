"""Duplas de teste (fakes) pro DlcService — mesmo padrao de
tests/_fakes_product.py e tests/_fakes_role_sync.py: substitui a sessao real
por dicts em memoria, so trocando a camada de persistencia (a logica de
negocio real do service continua sob teste)."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

from database.models.plan import Plan
from database.models.player import Player
from database.models.product import Product, ProductType


@dataclass
class DlcFakeStore:
    products: dict[uuid.UUID, Product] = field(default_factory=dict)
    plans: dict[uuid.UUID, Plan] = field(default_factory=dict)
    players: dict[uuid.UUID, Player] = field(default_factory=dict)
    verified_role_id_by_guild: dict[int, int] = field(default_factory=dict)


class FakeSession:
    async def flush(self) -> None:
        pass

    async def refresh(self, entity: object) -> None:
        pass


class FakeDatabase:
    def __init__(self, store: DlcFakeStore) -> None:
        self.store = store

    @asynccontextmanager
    async def session(self):
        yield FakeSession()


def _new_id(entity: object) -> None:
    if getattr(entity, "id", None) is None:
        entity.id = uuid.uuid4()


class FakeProductRepository:
    def __init__(self, session: FakeSession, *, store: DlcFakeStore) -> None:
        self._store = store

    async def add(self, entity: Product) -> Product:
        _new_id(entity)
        self._store.products[entity.id] = entity
        return entity

    async def get_by_id(self, id_: uuid.UUID, *, include_deleted: bool = False) -> Product | None:
        product = self._store.products.get(id_)
        if product is not None and product.deleted_at is not None and not include_deleted:
            return None
        return product

    async def get_by_slug(self, slug: str, *, include_deleted: bool = False) -> Product | None:
        for product in self._store.products.values():
            if product.slug == slug and (include_deleted or product.deleted_at is None):
                return product
        return None

    async def list_catalog(self, *, only_active: bool = True) -> list[Product]:
        items = [p for p in self._store.products.values() if p.deleted_at is None]
        if only_active:
            items = [p for p in items if p.is_active]
        return sorted(items, key=lambda p: (p.position, p.name))

    async def list_dlc(self, *, only_active: bool = False) -> list[Product]:
        items = [
            p
            for p in self._store.products.values()
            if p.deleted_at is None and p.product_type == ProductType.DLC
        ]
        if only_active:
            items = [p for p in items if p.is_active]
        return sorted(items, key=lambda p: (p.position, p.name))

    async def list_free_dlc_by_guild(self, guild_id: int) -> list[Product]:
        return [
            p
            for p in self._store.products.values()
            if p.deleted_at is None
            and p.is_active
            and p.product_type == ProductType.DLC
            and p.required_role_guild_id == guild_id
            and p.required_role_id is not None
        ]


class FakePlanRepository:
    def __init__(self, session: FakeSession, *, store: DlcFakeStore) -> None:
        self._store = store

    async def add(self, entity: Plan) -> Plan:
        _new_id(entity)
        if entity.created_at is None:
            entity.created_at = datetime.now(UTC)
        self._store.plans[entity.id] = entity
        return entity

    async def get_by_id(self, id_: uuid.UUID) -> Plan | None:
        return self._store.plans.get(id_)

    async def list_by_product(self, product_id: uuid.UUID) -> list[Plan]:
        """Espelha o `ORDER BY created_at ASC` de PlanRepository.list_by_product
        real — mesmo contrato de determinismo que DlcService.get_purchase_plan
        depende (ver database/repositories/plan_repository.py)."""
        items = [p for p in self._store.plans.values() if p.product_id == product_id]
        return sorted(items, key=lambda p: p.created_at)

    async def list_by_guild(self, guild_id: int, *, only_active: bool = False) -> list[Plan]:
        items = [p for p in self._store.plans.values() if p.guild_id == guild_id]
        if only_active:
            items = [p for p in items if p.is_active]
        return items


class FakePlayerRepository:
    def __init__(self, session: FakeSession, *, store: DlcFakeStore) -> None:
        self._store = store

    async def get_by_discord_id(self, discord_id: int) -> Player | None:
        return next((p for p in self._store.players.values() if p.discord_id == discord_id), None)

    async def get_or_create_by_discord_id(
        self, discord_id: int, *, discord_username: str | None, linked_at: object
    ) -> Player:
        player = await self.get_by_discord_id(discord_id)
        if player is not None:
            return player
        player = Player(discord_id=discord_id, discord_username=discord_username, linked_at=linked_at)
        _new_id(player)
        self._store.players[player.id] = player
        return player

    async def list_by_discord_ids(self, discord_ids: list[int]) -> list[Player]:
        wanted = set(discord_ids)
        return [p for p in self._store.players.values() if p.discord_id in wanted]

    async def list_by_ids(self, ids: list[uuid.UUID]) -> list[Player]:
        wanted = set(ids)
        return [p for p in self._store.players.values() if p.id in wanted]


class _FakeGuildSettings:
    def __init__(self, verified_role_id: int | None) -> None:
        self.verified_role_id = verified_role_id


class FakeGuildSettingsRepository:
    def __init__(self, session: FakeSession, *, store: DlcFakeStore) -> None:
        self._store = store

    async def get_by_guild_id(self, guild_id: int) -> _FakeGuildSettings | None:
        role_id = self._store.verified_role_id_by_guild.get(guild_id)
        if role_id is None:
            return None
        return _FakeGuildSettings(role_id)


def install_dlc_fakes(monkeypatch, store: DlcFakeStore) -> None:
    monkeypatch.setattr(
        "services.dlc_service.ProductRepository", lambda session: FakeProductRepository(session, store=store)
    )
    monkeypatch.setattr(
        "services.dlc_service.PlanRepository", lambda session: FakePlanRepository(session, store=store)
    )
    monkeypatch.setattr(
        "services.dlc_service.PlayerRepository", lambda session: FakePlayerRepository(session, store=store)
    )
    monkeypatch.setattr(
        "services.dlc_service.GuildSettingsRepository",
        lambda session: FakeGuildSettingsRepository(session, store=store),
    )
    # DlcService instancia ProductService internamente — mesmo store, modulo diferente.
    monkeypatch.setattr(
        "services.product_service.ProductRepository", lambda session: FakeProductRepository(session, store=store)
    )
