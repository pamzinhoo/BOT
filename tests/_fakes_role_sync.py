"""Duplas de teste (fakes) pro RoleSyncService/ReconciliationService."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from database.models.license import License, LicenseStatus
from database.models.plan import Plan
from database.models.player import Player


@dataclass
class RoleSyncFakeStore:
    players: dict[uuid.UUID, Player] = field(default_factory=dict)
    plans: list[Plan] = field(default_factory=list)
    licenses: dict[uuid.UUID, License] = field(default_factory=dict)
    audit_calls: list[dict] = field(default_factory=list)


class FakeSession:
    async def flush(self) -> None:
        pass

    async def refresh(self, entity: object) -> None:
        pass


class FakeDatabase:
    def __init__(self, store: RoleSyncFakeStore) -> None:
        self.store = store

    @asynccontextmanager
    async def session(self):
        yield FakeSession()


class FakePlayerRepository:
    def __init__(self, session: FakeSession, *, store: RoleSyncFakeStore) -> None:
        self._store = store

    async def get_by_id(self, id_: uuid.UUID) -> Player | None:
        return self._store.players.get(id_)

    async def get_by_discord_id(self, discord_id: int) -> Player | None:
        return next((p for p in self._store.players.values() if p.discord_id == discord_id), None)

    async def list_by_discord_ids(self, discord_ids: list[int]) -> list[Player]:
        wanted = set(discord_ids)
        return [p for p in self._store.players.values() if p.discord_id in wanted]

    async def list_by_ids(self, ids: list[uuid.UUID]) -> list[Player]:
        wanted = set(ids)
        return [p for p in self._store.players.values() if p.id in wanted]


class FakePlanRepository:
    def __init__(self, session: FakeSession, *, store: RoleSyncFakeStore) -> None:
        self._store = store

    async def list_by_product(self, product_id: uuid.UUID) -> list[Plan]:
        return [p for p in self._store.plans if p.product_id == product_id and p.role_id is not None]

    async def list_by_guild(self, guild_id: int, *, only_active: bool = False) -> list[Plan]:
        return [p for p in self._store.plans if p.guild_id == guild_id]


class FakeLicenseRepository:
    def __init__(self, session: FakeSession, *, store: RoleSyncFakeStore) -> None:
        self._store = store

    async def has_active_license(self, player_id: uuid.UUID, product_id: uuid.UUID) -> bool:
        return any(
            lic.player_id == player_id and lic.product_id == product_id and lic.status == LicenseStatus.ACTIVE
            for lic in self._store.licenses.values()
        )

    async def list_active_by_product(self, product_id: uuid.UUID) -> list[License]:
        return [
            lic
            for lic in self._store.licenses.values()
            if lic.product_id == product_id and lic.status == LicenseStatus.ACTIVE
        ]

    async def list_active_by_players_and_product(
        self, player_ids: list[uuid.UUID], product_id: uuid.UUID
    ) -> list[License]:
        wanted = set(player_ids)
        return [
            lic
            for lic in self._store.licenses.values()
            if lic.player_id in wanted and lic.product_id == product_id and lic.status == LicenseStatus.ACTIVE
        ]


class FakeAuditLogService:
    def __init__(self, store: RoleSyncFakeStore) -> None:
        self._store = store

    async def record(self, **kwargs) -> None:
        self._store.audit_calls.append(kwargs)


def install_role_sync_fakes(monkeypatch, store: RoleSyncFakeStore) -> None:
    monkeypatch.setattr(
        "services.role_sync_service.PlayerRepository", lambda session: FakePlayerRepository(session, store=store)
    )
    monkeypatch.setattr(
        "services.role_sync_service.PlanRepository", lambda session: FakePlanRepository(session, store=store)
    )


def install_reconciliation_fakes(monkeypatch, store: RoleSyncFakeStore) -> None:
    monkeypatch.setattr(
        "services.reconciliation_service.PlayerRepository", lambda session: FakePlayerRepository(session, store=store)
    )
    monkeypatch.setattr(
        "services.reconciliation_service.PlanRepository", lambda session: FakePlanRepository(session, store=store)
    )
    monkeypatch.setattr(
        "services.reconciliation_service.LicenseRepository",
        lambda session: FakeLicenseRepository(session, store=store),
    )
