"""Testes de regressao pra Fase 2 da auditoria de performance
(docs/AUDITORIA_PERFORMANCE_2.md): cache negativo de canal de ticket,
cache de staff, log/audit log em background, e cache de settings que ainda
nao tinham (evaluation/dashboard/bot_status/ranking)."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from database.models.staff import Staff
from database.models.ticket import Ticket, TicketCategory, TicketStatus
from database.models.ticket_message import TicketMessageKind
from services.audit_log_service import AuditLogService
from services.config_service import ConfigService
from services.log_service import LogService
from services.staff_service import StaffService
from services.ticket_service import TicketService


class _FakeSession:
    async def flush(self) -> None:
        pass


class _FakeDatabase:
    """Conta quantas vezes uma sessao foi aberta — serve de proxy pro numero
    de round-trips seriais ao banco nos testes abaixo."""

    def __init__(self) -> None:
        self.session_count = 0

    @asynccontextmanager
    async def session(self):
        self.session_count += 1
        yield _FakeSession()


# --- TicketService: cache negativo de canal (A8 da auditoria original) -----


def _make_ticket(**overrides: object) -> Ticket:
    defaults = dict(
        id=uuid.uuid4(),
        guild_id=1,
        channel_id=999,
        opened_by_discord_id=111,
        category=TicketCategory.OUTRO,
        status=TicketStatus.OPEN,
        first_response_at=None,
    )
    defaults.update(overrides)
    return Ticket(**defaults)


class _FakeTicketRepo:
    def __init__(self, session: _FakeSession, *, store: dict) -> None:
        self._store = store

    async def get_by_channel_id(self, channel_id: int) -> Ticket | None:
        self._store["calls"] = self._store.get("calls", 0) + 1
        return self._store["tickets"].get(channel_id)


async def test_get_by_channel_id_caches_negative_result(monkeypatch) -> None:
    database = _FakeDatabase()
    store = {"tickets": {}, "calls": 0}
    monkeypatch.setattr(
        "services.ticket_service.TicketRepository",
        lambda session: _FakeTicketRepo(session, store=store),
    )
    service = TicketService(database)

    result1 = await service.get_by_channel_id(555)
    result2 = await service.get_by_channel_id(555)

    assert result1 is None
    assert result2 is None
    # segunda chamada nao deveria abrir sessao nenhuma — canal ja confirmado
    # como "nao e ticket".
    assert database.session_count == 1
    assert store["calls"] == 1


async def test_get_by_channel_id_does_not_cache_positive_result(monkeypatch) -> None:
    """Ticket EXISTE — precisa continuar buscando fresco toda vez (status/claim
    mudam a todo momento, nao pode ficar desatualizado)."""
    database = _FakeDatabase()
    ticket = _make_ticket()
    store = {"tickets": {ticket.channel_id: ticket}, "calls": 0}
    monkeypatch.setattr(
        "services.ticket_service.TicketRepository",
        lambda session: _FakeTicketRepo(session, store=store),
    )
    service = TicketService(database)

    await service.get_by_channel_id(ticket.channel_id)
    await service.get_by_channel_id(ticket.channel_id)

    assert database.session_count == 2
    assert store["calls"] == 2


async def test_forget_channel_clears_negative_cache(monkeypatch) -> None:
    database = _FakeDatabase()
    store = {"tickets": {}, "calls": 0}
    monkeypatch.setattr(
        "services.ticket_service.TicketRepository",
        lambda session: _FakeTicketRepo(session, store=store),
    )
    service = TicketService(database)

    await service.get_by_channel_id(777)
    service.forget_channel(777)
    await service.get_by_channel_id(777)

    assert database.session_count == 2
    assert store["calls"] == 2


class _FakeTicketMessageRepo:
    def __init__(self, session: _FakeSession, *, store: dict) -> None:
        self._store = store

    async def exists(self, ticket_id, kind) -> bool:
        return (ticket_id, kind) in self._store.get("messages", set())

    async def add(self, message) -> object:
        self._store.setdefault("messages", set()).add((message.ticket_id, message.kind))
        self._store.setdefault("added", []).append(message)
        return message


async def test_record_first_message_for_channel_single_session_for_ticket(monkeypatch) -> None:
    """Antes: on_message fazia get_by_channel_id, e record_first_message
    reabria uma sessao pra buscar o MESMO ticket de novo (2 round-trips pra
    canais de ticket). Agora e 1 so."""
    database = _FakeDatabase()
    ticket = _make_ticket()
    store = {"tickets": {ticket.channel_id: ticket}, "calls": 0}
    monkeypatch.setattr(
        "services.ticket_service.TicketRepository",
        lambda session: _FakeTicketRepo(session, store=store),
    )
    monkeypatch.setattr(
        "services.ticket_service.TicketMessageRepository",
        lambda session: _FakeTicketMessageRepo(session, store=store),
    )
    service = TicketService(database)

    message = SimpleNamespace(
        channel=SimpleNamespace(id=ticket.channel_id),
        author=SimpleNamespace(id=ticket.opened_by_discord_id, bot=False),
        id=42,
        created_at=datetime.now(UTC),
    )

    await service.record_first_message_for_channel(message)  # type: ignore[arg-type]

    assert database.session_count == 1
    assert store["calls"] == 1
    assert (ticket.id, TicketMessageKind.USER_FIRST) in store["messages"]


async def test_record_first_message_for_channel_skips_confirmed_non_ticket(monkeypatch) -> None:
    database = _FakeDatabase()
    store = {"tickets": {}, "calls": 0}
    monkeypatch.setattr(
        "services.ticket_service.TicketRepository",
        lambda session: _FakeTicketRepo(session, store=store),
    )
    monkeypatch.setattr(
        "services.ticket_service.TicketMessageRepository",
        lambda session: _FakeTicketMessageRepo(session, store=store),
    )
    service = TicketService(database)
    message = SimpleNamespace(
        channel=SimpleNamespace(id=321),
        author=SimpleNamespace(id=1, bot=False),
        id=1,
        created_at=datetime.now(UTC),
    )

    await service.record_first_message_for_channel(message)  # type: ignore[arg-type]
    await service.record_first_message_for_channel(message)  # type: ignore[arg-type]

    assert database.session_count == 1
    assert store["calls"] == 1


# --- StaffService: cache de ensure_staff --------------------------------


class _FakeStaffRepo:
    def __init__(self, session: _FakeSession, *, store: dict) -> None:
        self._store = store

    async def get_by_discord_id(self, guild_id: int, discord_user_id: int) -> Staff | None:
        self._store["calls"] = self._store.get("calls", 0) + 1
        return self._store["staff"].get((guild_id, discord_user_id))

    async def add(self, entity: Staff) -> Staff:
        self._store["staff"][(entity.guild_id, entity.discord_user_id)] = entity
        return entity


async def test_ensure_staff_uses_cache_when_display_name_unchanged(monkeypatch) -> None:
    database = _FakeDatabase()
    existing = Staff(id=uuid.uuid4(), guild_id=1, discord_user_id=2, display_name="Fulano")
    store = {"staff": {(1, 2): existing}, "calls": 0}
    monkeypatch.setattr(
        "services.staff_service.StaffRepository",
        lambda session: _FakeStaffRepo(session, store=store),
    )
    service = StaffService(database)

    first = await service.ensure_staff(1, 2, "Fulano")
    second = await service.ensure_staff(1, 2, "Fulano")

    assert first is existing
    assert second is existing
    assert database.session_count == 1
    assert store["calls"] == 1


async def test_ensure_staff_refreshes_when_display_name_changes(monkeypatch) -> None:
    database = _FakeDatabase()
    existing = Staff(id=uuid.uuid4(), guild_id=1, discord_user_id=2, display_name="Fulano")
    store = {"staff": {(1, 2): existing}, "calls": 0}
    monkeypatch.setattr(
        "services.staff_service.StaffRepository",
        lambda session: _FakeStaffRepo(session, store=store),
    )
    service = StaffService(database)

    await service.ensure_staff(1, 2, "Fulano")
    updated = await service.ensure_staff(1, 2, "Fulano (novo nick)")

    assert updated.display_name == "Fulano (novo nick)"
    assert database.session_count == 2


# --- LogService / AuditLogService: fire-and-forget opt-in -------------------


async def test_log_service_record_background_calls_record_and_returns_immediately() -> None:
    database = _FakeDatabase()
    bot = SimpleNamespace()
    service = LogService(database, bot)  # type: ignore[arg-type]
    service.record = AsyncMock(return_value=None)  # type: ignore[method-assign]

    service.record_background(guild_id=1, action="claim", message="oi")  # type: ignore[arg-type]
    assert service.record.await_count == 0  # nao foi esperado ainda, so agendado

    await asyncio.sleep(0)  # deixa a task rodar
    await asyncio.sleep(0)

    service.record.assert_awaited_once()


async def test_log_service_record_background_swallows_exceptions() -> None:
    database = _FakeDatabase()
    bot = SimpleNamespace()
    service = LogService(database, bot)  # type: ignore[arg-type]
    service.record = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]

    service.record_background(guild_id=1, action="claim", message="oi")  # type: ignore[arg-type]

    for _ in range(5):
        await asyncio.sleep(0)

    # nao deve propagar — se propagasse, este teste teria estourado a excecao
    # acima. Task some do set de background depois de concluida.
    assert len(service._background_tasks) == 0


async def test_audit_log_service_record_background_calls_record() -> None:
    database = _FakeDatabase()
    bot = SimpleNamespace()
    service = AuditLogService(database, bot)  # type: ignore[arg-type]
    service.record = AsyncMock(return_value=None)  # type: ignore[method-assign]

    service.record_background(guild_id=1, category="tickets", action="x")

    await asyncio.sleep(0)
    await asyncio.sleep(0)

    service.record.assert_awaited_once()


# --- ConfigService: caches novos (evaluation/dashboard/bot_status/ranking) --


class _FakeSettingsRepo:
    def __init__(self, session: _FakeSession, *, store: dict, key: str) -> None:
        self._store = store
        self._key = key

    async def get_or_create(self, guild_id: int):
        self._store["calls"] = self._store.get("calls", 0) + 1
        obj = self._store["objs"].setdefault(guild_id, SimpleNamespace(guild_id=guild_id, x=1))
        return obj


async def test_get_evaluation_settings_is_cached_and_invalidated_on_update(monkeypatch) -> None:
    database = _FakeDatabase()
    store = {"objs": {}, "calls": 0}
    monkeypatch.setattr(
        "services.config_service.EvaluationSettingsRepository",
        lambda session: _FakeSettingsRepo(session, store=store, key="evaluation"),
    )
    service = ConfigService(database)

    first = await service.get_evaluation_settings(10)
    second = await service.get_evaluation_settings(10)
    assert first is second
    assert store["calls"] == 1

    await service.update_evaluation_settings(10, x=2)
    await service.get_evaluation_settings(10)
    assert store["calls"] == 3  # 1 (get) + 1 (update) + 1 (get pos-invalidate)
