"""Duplas de teste (fakes) pro fluxo de auth do Launcher — nao e um arquivo
`test_*`, entao o pytest nao coleta ele direto, so importa. Substitui a
sessao real do SQLAlchemy por dicts em memoria: os models usam tipos
Postgres-only (UUID, INET, JSONB, Enum com dialect postgres) que nao rodam
contra SQLite, e o resto do repo tambem nao usa Postgres real em teste (ver
tests/test_verification_service.py) — monkeypatch nas classes de repository
importadas dentro de services/auth_service.py mantem a logica de negocio
real sob teste, so troca a camada de persistencia.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field


@dataclass
class AuthFakeStore:
    players: dict[uuid.UUID, object] = field(default_factory=dict)
    devices: dict[uuid.UUID, object] = field(default_factory=dict)
    sessions: dict[uuid.UUID, object] = field(default_factory=dict)
    audit_logs: list[object] = field(default_factory=list)


class FakeSession:
    async def flush(self) -> None:
        pass


class FakeDatabase:
    def __init__(self, store: AuthFakeStore) -> None:
        self.store = store

    @asynccontextmanager
    async def session(self):
        yield FakeSession()


def _new_id(entity) -> None:
    if getattr(entity, "id", None) is None:
        entity.id = uuid.uuid4()


class FakePlayerRepository:
    def __init__(self, session: FakeSession, *, store: AuthFakeStore) -> None:
        self._store = store

    async def get_by_discord_id(self, discord_id: int):
        return next((p for p in self._store.players.values() if p.discord_id == discord_id), None)

    async def get_or_create_by_discord_id(self, discord_id: int, *, discord_username, linked_at):
        from database.models.player import Player

        player = await self.get_by_discord_id(discord_id)
        if player is None:
            player = Player(discord_id=discord_id, discord_username=discord_username, linked_at=linked_at)
            player.is_banned = False
            player.last_login_at = None
            player.last_login_ip = None
            _new_id(player)
            self._store.players[player.id] = player
            return player
        if discord_username is not None:
            player.discord_username = discord_username
        return player

    async def get_by_id(self, id_):
        return self._store.players.get(id_)


class FakeDeviceRepository:
    def __init__(self, session: FakeSession, *, store: AuthFakeStore) -> None:
        self._store = store

    async def get_by_player_and_uuid(self, player_id, device_uuid):
        return next(
            (
                d
                for d in self._store.devices.values()
                if d.player_id == player_id and d.device_uuid == device_uuid
            ),
            None,
        )

    async def add(self, entity):
        _new_id(entity)
        self._store.devices[entity.id] = entity
        return entity

    async def get_by_id(self, id_):
        return self._store.devices.get(id_)

    async def list_active_by_player(self, player_id):
        return [d for d in self._store.devices.values() if d.player_id == player_id and not d.revoked]


class FakeLauncherSessionRepository:
    def __init__(self, session: FakeSession, *, store: AuthFakeStore) -> None:
        self._store = store

    async def add(self, entity):
        _new_id(entity)
        self._store.sessions[entity.id] = entity
        return entity

    async def get_by_token_hash(self, refresh_token_hash: str):
        return next(
            (s for s in self._store.sessions.values() if s.refresh_token_hash == refresh_token_hash), None
        )

    async def get_by_id(self, id_):
        return self._store.sessions.get(id_)

    async def list_active_by_device(self, device_id):
        return [
            s for s in self._store.sessions.values() if s.device_id == device_id and s.revoked_at is None
        ]

    async def revoke_all_for_device(self, device_id, *, reason: str, revoked_at):
        for s in await self.list_active_by_device(device_id):
            s.revoked_at = revoked_at
            s.revoked_reason = reason


class FakeAuditLogLauncherRepository:
    def __init__(self, session: FakeSession, *, store: AuthFakeStore) -> None:
        self._store = store

    async def record(self, *, action, player_id=None, device_id=None, ip_address=None, metadata=None):
        entry = {
            "action": action,
            "player_id": player_id,
            "device_id": device_id,
            "ip_address": ip_address,
            "metadata": metadata or {},
        }
        self._store.audit_logs.append(entry)
        return entry


def install_fake_repositories(monkeypatch, store: AuthFakeStore) -> None:
    """Troca os repositorios usados dentro de services.auth_service por
    fakes ligados a `store`, mantendo o resto da logica do AuthService real."""
    monkeypatch.setattr(
        "services.auth_service.PlayerRepository", lambda session: FakePlayerRepository(session, store=store)
    )
    monkeypatch.setattr(
        "services.auth_service.DeviceRepository", lambda session: FakeDeviceRepository(session, store=store)
    )
    monkeypatch.setattr(
        "services.auth_service.LauncherSessionRepository",
        lambda session: FakeLauncherSessionRepository(session, store=store),
    )
    monkeypatch.setattr(
        "services.auth_service.AuditLogLauncherRepository",
        lambda session: FakeAuditLogLauncherRepository(session, store=store),
    )
