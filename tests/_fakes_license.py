"""Duplas de teste (fakes) pro LicenseService — mesmo padrao de
tests/_fakes_auth.py: substitui a sessao real do SQLAlchemy por dicts em
memoria, porque License usa tipos Postgres-only (UUID, JSONB, Enum nativo)
que nao rodam contra SQLite. monkeypatch nas classes de repository
importadas dentro de services/license_service.py mantem a logica de negocio
real sob teste, so troca a camada de persistencia.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from database.models.license import License, LicenseStatus


@dataclass
class LicenseFakeStore:
    licenses: dict[uuid.UUID, License] = field(default_factory=dict)
    events: list[object] = field(default_factory=list)


class FakeSession:
    async def flush(self) -> None:
        pass

    async def refresh(self, entity: object) -> None:
        pass


class FakeDatabase:
    def __init__(self, store: LicenseFakeStore) -> None:
        self.store = store

    @asynccontextmanager
    async def session(self):
        yield FakeSession()


def _new_id(entity: object) -> None:
    if getattr(entity, "id", None) is None:
        entity.id = uuid.uuid4()


class FakeLicenseRepository:
    def __init__(self, session: FakeSession, *, store: LicenseFakeStore) -> None:
        self._store = store

    async def add(self, entity: License) -> License:
        _new_id(entity)
        self._store.licenses[entity.id] = entity
        return entity

    async def get_by_id(self, id_: uuid.UUID) -> License | None:
        return self._store.licenses.get(id_)

    async def get_by_id_locked(self, id_: uuid.UUID) -> License | None:
        # sem concorrencia real em memoria — FOR UPDATE nao tem efeito aqui,
        # so precisa expor a mesma assinatura que LicenseRepository real
        return self._store.licenses.get(id_)

    async def get_by_player_product(self, player_id: uuid.UUID, product_id: uuid.UUID) -> License | None:
        return next(
            (
                lic
                for lic in self._store.licenses.values()
                if lic.player_id == player_id and lic.product_id == product_id
            ),
            None,
        )

    async def list_by_player(self, player_id: uuid.UUID) -> list[License]:
        return [lic for lic in self._store.licenses.values() if lic.player_id == player_id]

    async def list_active_by_player(self, player_id: uuid.UUID) -> list[License]:
        return [
            lic
            for lic in self._store.licenses.values()
            if lic.player_id == player_id and lic.status == LicenseStatus.ACTIVE
        ]

    async def has_active_license(self, player_id: uuid.UUID, product_id: uuid.UUID) -> bool:
        lic = await self.get_by_player_product(player_id, product_id)
        return lic is not None and lic.status == LicenseStatus.ACTIVE

    async def list_active_by_product(self, product_id: uuid.UUID) -> list[License]:
        return [
            lic
            for lic in self._store.licenses.values()
            if lic.product_id == product_id and lic.status == LicenseStatus.ACTIVE
        ]


class FakeLicenseEventRepository:
    def __init__(self, session: FakeSession, *, store: LicenseFakeStore) -> None:
        self._store = store

    async def add(self, entity: object) -> object:
        _new_id(entity)
        self._store.events.append(entity)
        return entity


def install_fake_repositories(monkeypatch, store: LicenseFakeStore) -> None:
    monkeypatch.setattr(
        "services.license_service.LicenseRepository",
        lambda session: FakeLicenseRepository(session, store=store),
    )
    monkeypatch.setattr(
        "services.license_service.LicenseEventRepository",
        lambda session: FakeLicenseEventRepository(session, store=store),
    )
