"""Testes de regressao pra FASE 1 da otimizacao global de performance
(docs/AUDITORIA_GLOBAL_PERFORMANCE.md): cache de settings do AutoMod, cache
da lista efetiva de palavras do AutoMod, e cache de settings do AuditLog —
os dois gargalos de maior prioridade da auditoria, fora do sistema de
Tickets. Mesmo padrao (TTLCache + invalidacao explicita na escrita) e mesmo
estilo de teste (_FakeDatabase que conta sessoes abertas) ja usados em
tests/test_perf_audit_2.py."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

from database.models.audit_log_settings import AuditLogSettings
from services.audit_log_service import AuditLogService
from services.automod_service import AutoModService, EffectiveWord
from utils.automod_wordlist import DEFAULT_WORDS_BY_TEXT


class _FakeSession:
    async def flush(self) -> None:
        pass

    async def refresh(self, _obj: object) -> None:
        pass


class _FakeDatabase:
    """Conta quantas vezes uma sessao foi aberta — proxy pro numero de
    round-trips seriais ao banco."""

    def __init__(self) -> None:
        self.session_count = 0

    @asynccontextmanager
    async def session(self):
        self.session_count += 1
        yield _FakeSession()


# =========================== AutoModService.get_settings ====================


class _FakeAutoModSettingsRepo:
    def __init__(self, session: _FakeSession, *, store: dict) -> None:
        self._store = store

    async def get_or_create(self, guild_id: int):
        self._store["calls"] = self._store.get("calls", 0) + 1
        return self._store["objs"].setdefault(
            guild_id, SimpleNamespace(guild_id=guild_id, enabled=True)
        )


async def test_automod_get_settings_is_cached_and_invalidated_on_update(monkeypatch) -> None:
    database = _FakeDatabase()
    store = {"objs": {}, "calls": 0}
    monkeypatch.setattr(
        "services.automod_service.AutoModSettingsRepository",
        lambda session: _FakeAutoModSettingsRepo(session, store=store),
    )
    service = AutoModService(database)  # type: ignore[arg-type]

    first = await service.get_settings(10)
    second = await service.get_settings(10)
    assert first is second
    assert store["calls"] == 1  # 2a chamada veio do cache, sem round-trip

    await service.update_settings(10, enabled=False)
    await service.get_settings(10)
    assert store["calls"] == 3  # 1 (get) + 1 (update) + 1 (get pos-invalidate)


async def test_automod_get_settings_does_not_mix_different_guilds(monkeypatch) -> None:
    database = _FakeDatabase()
    store = {"objs": {}, "calls": 0}
    monkeypatch.setattr(
        "services.automod_service.AutoModSettingsRepository",
        lambda session: _FakeAutoModSettingsRepo(session, store=store),
    )
    service = AutoModService(database)  # type: ignore[arg-type]

    settings_a = await service.get_settings(111)
    settings_b = await service.get_settings(222)
    assert settings_a.guild_id == 111
    assert settings_b.guild_id == 222
    assert store["calls"] == 2  # cada guild paga sua propria 1a consulta

    # cache hit de A nao deve ser afetado por B ter sido consultada depois
    settings_a_again = await service.get_settings(111)
    assert settings_a_again is settings_a
    assert store["calls"] == 2


# =========================== AutoModService.list_effective_words ============


class _FakeAutoModWordRepo:
    def __init__(self, session: _FakeSession, *, store: dict) -> None:
        self._store = store

    async def list_by_guild(self, guild_id: int) -> list:
        self._store["list_calls"] = self._store.get("list_calls", 0) + 1
        return self._store.get("overrides", {}).get(guild_id, [])

    async def get_by_word(self, guild_id: int, palavra: str):
        return None

    async def add(self, word: object) -> object:
        return word

    async def delete(self, word: object) -> None:
        pass


async def test_list_effective_words_is_cached(monkeypatch) -> None:
    database = _FakeDatabase()
    store: dict = {"list_calls": 0, "overrides": {}}
    monkeypatch.setattr(
        "services.automod_service.AutoModWordRepository",
        lambda session: _FakeAutoModWordRepo(session, store=store),
    )
    service = AutoModService(database)  # type: ignore[arg-type]

    first = await service.list_effective_words(10)
    second = await service.list_effective_words(10)
    assert store["list_calls"] == 1
    assert [w.palavra for w in first] == [w.palavra for w in second]
    # inclui a palavra padrao embutida no codigo (nao depende do banco)
    assert len(first) == len(DEFAULT_WORDS_BY_TEXT)


async def test_list_effective_words_returns_independent_copies(monkeypatch) -> None:
    """O cache guarda a lista internamente — mutar o que o caller recebeu
    nao pode vazar pro proximo cache hit."""
    database = _FakeDatabase()
    store: dict = {"list_calls": 0, "overrides": {}}
    monkeypatch.setattr(
        "services.automod_service.AutoModWordRepository",
        lambda session: _FakeAutoModWordRepo(session, store=store),
    )
    service = AutoModService(database)  # type: ignore[arg-type]

    first = await service.list_effective_words(10)
    first.append(EffectiveWord("hack-de-teste", first[0].categoria, first[0].nivel, is_builtin=False))
    second = await service.list_effective_words(10)
    assert len(second) == len(DEFAULT_WORDS_BY_TEXT)  # nao ganhou a palavra injetada


async def test_add_word_invalidates_words_cache(monkeypatch) -> None:
    database = _FakeDatabase()
    store: dict = {"list_calls": 0, "overrides": {}}
    monkeypatch.setattr(
        "services.automod_service.AutoModWordRepository",
        lambda session: _FakeAutoModWordRepo(session, store=store),
    )
    service = AutoModService(database)  # type: ignore[arg-type]

    await service.list_effective_words(10)
    assert store["list_calls"] == 1

    await service.add_word(10, "palavra-nova")
    await service.list_effective_words(10)
    assert store["list_calls"] == 2  # cache invalidado, releu do banco


# =========================== AuditLogService.get_settings ===================


class _FakeAuditLogSettingsRepo:
    def __init__(self, session: _FakeSession, *, store: dict) -> None:
        self._store = store

    async def get_or_create(self, guild_id: int):
        self._store["calls"] = self._store.get("calls", 0) + 1
        return self._store["objs"].setdefault(
            guild_id, SimpleNamespace(guild_id=guild_id, tickets=True, ban=True)
        )


async def test_audit_log_get_settings_is_cached_and_invalidated_on_update(monkeypatch) -> None:
    database = _FakeDatabase()
    store: dict = {"objs": {}, "calls": 0}
    monkeypatch.setattr(
        "services.audit_log_service.AuditLogSettingsRepository",
        lambda session: _FakeAuditLogSettingsRepo(session, store=store),
    )
    service = AuditLogService(database, bot=SimpleNamespace())  # type: ignore[arg-type]

    first = await service.get_settings(10)
    second = await service.get_settings(10)
    assert first is second
    assert store["calls"] == 1

    await service.update_settings(10, ban=False)
    await service.get_settings(10)
    assert store["calls"] == 3


class _FakeAuditLogSettingsRepoRealModel:
    """Igual a `_FakeAuditLogSettingsRepo`, mas devolve uma instancia real do
    model — `reset_row` precisa de `__table__` (nao funciona com SimpleNamespace)."""

    def __init__(self, session: _FakeSession, *, store: dict) -> None:
        self._store = store

    async def get_or_create(self, guild_id: int):
        self._store["calls"] = self._store.get("calls", 0) + 1
        return self._store["objs"].setdefault(
            guild_id, AuditLogSettings(guild_id=guild_id, ban=False)
        )


async def test_audit_log_get_settings_invalidated_on_reset(monkeypatch) -> None:
    database = _FakeDatabase()
    store: dict = {"objs": {}, "calls": 0}
    monkeypatch.setattr(
        "services.audit_log_service.AuditLogSettingsRepository",
        lambda session: _FakeAuditLogSettingsRepoRealModel(session, store=store),
    )
    service = AuditLogService(database, bot=SimpleNamespace())  # type: ignore[arg-type]

    await service.get_settings(10)
    await service.reset_settings(10)
    await service.get_settings(10)
    assert store["calls"] == 3  # get + reset + get pos-invalidate


async def test_audit_log_get_settings_does_not_mix_different_guilds(monkeypatch) -> None:
    database = _FakeDatabase()
    store: dict = {"objs": {}, "calls": 0}
    monkeypatch.setattr(
        "services.audit_log_service.AuditLogSettingsRepository",
        lambda session: _FakeAuditLogSettingsRepo(session, store=store),
    )
    service = AuditLogService(database, bot=SimpleNamespace())  # type: ignore[arg-type]

    a = await service.get_settings(111)
    b = await service.get_settings(222)
    assert a.guild_id == 111
    assert b.guild_id == 222
    assert store["calls"] == 2
