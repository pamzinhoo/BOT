"""Duplas de teste (fakes) pro PollService — mesmo padrao de
tests/_fakes_dlc.py: substitui a sessao real por dicts em memoria, so
trocando a camada de persistencia (a logica de negocio real do service
continua sob teste)."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from database.models.enquete_settings import EnqueteSettings
from database.models.poll import Poll, PollOption, PollVote


@dataclass
class PollFakeStore:
    polls: dict[uuid.UUID, Poll] = field(default_factory=dict)
    options: dict[uuid.UUID, PollOption] = field(default_factory=dict)
    votes: dict[uuid.UUID, PollVote] = field(default_factory=dict)
    settings: dict[int, EnqueteSettings] = field(default_factory=dict)


class FakeSession:
    async def flush(self) -> None:
        pass

    async def refresh(self, entity: object) -> None:
        pass


class FakeDatabase:
    def __init__(self, store: PollFakeStore) -> None:
        self.store = store

    @asynccontextmanager
    async def session(self):
        yield FakeSession()


def _new_id(entity: object) -> None:
    if getattr(entity, "id", None) is None:
        entity.id = uuid.uuid4()


class FakePollRepository:
    def __init__(self, session: FakeSession, *, store: PollFakeStore) -> None:
        self._store = store

    async def add(self, entity: Poll) -> Poll:
        _new_id(entity)
        self._store.polls[entity.id] = entity
        return entity

    async def get_by_id(self, id_: uuid.UUID) -> Poll | None:
        return self._store.polls.get(id_)

    async def list_by_guild(self, guild_id: int) -> list[Poll]:
        return [p for p in self._store.polls.values() if p.guild_id == guild_id]

    async def list_open_expiring(self, before) -> list[Poll]:
        from database.models.poll import PollStatus

        return [
            p for p in self._store.polls.values()
            if p.status == PollStatus.OPEN and p.expires_at <= before
        ]


class FakePollOptionRepository:
    def __init__(self, session: FakeSession, *, store: PollFakeStore) -> None:
        self._store = store

    async def add(self, entity: PollOption) -> PollOption:
        _new_id(entity)
        self._store.options[entity.id] = entity
        return entity

    async def list_by_poll(self, poll_id: uuid.UUID) -> list[PollOption]:
        items = [o for o in self._store.options.values() if o.poll_id == poll_id]
        return sorted(items, key=lambda o: o.position)


class FakePollVoteRepository:
    def __init__(self, session: FakeSession, *, store: PollFakeStore) -> None:
        self._store = store

    async def add(self, entity: PollVote) -> PollVote:
        for existing in self._store.votes.values():
            if existing.poll_id == entity.poll_id and existing.user_id == entity.user_id:
                from sqlalchemy.exc import IntegrityError

                raise IntegrityError("uq_poll_vote_one_per_user", {}, Exception("duplicate"))
        _new_id(entity)
        self._store.votes[entity.id] = entity
        return entity

    async def delete(self, entity: PollVote) -> None:
        self._store.votes.pop(entity.id, None)

    async def get_by_poll_and_user(self, poll_id: uuid.UUID, user_id: int) -> PollVote | None:
        return next(
            (v for v in self._store.votes.values() if v.poll_id == poll_id and v.user_id == user_id), None
        )

    async def weighted_totals(self, poll_id: uuid.UUID) -> dict[uuid.UUID, int]:
        totals: dict[uuid.UUID, int] = {}
        for vote in self._store.votes.values():
            if vote.poll_id == poll_id:
                totals[vote.option_id] = totals.get(vote.option_id, 0) + vote.weight
        return totals

    async def raw_totals(self, poll_id: uuid.UUID) -> dict[uuid.UUID, int]:
        totals: dict[uuid.UUID, int] = {}
        for vote in self._store.votes.values():
            if vote.poll_id == poll_id:
                totals[vote.option_id] = totals.get(vote.option_id, 0) + 1
        return totals

    async def totals(self, poll_id: uuid.UUID) -> dict[uuid.UUID, tuple[int, int]]:
        result: dict[uuid.UUID, tuple[int, int]] = {}
        for vote in self._store.votes.values():
            if vote.poll_id != poll_id:
                continue
            raw, weighted = result.get(vote.option_id, (0, 0))
            result[vote.option_id] = (raw + 1, weighted + vote.weight)
        return result

    async def count_participants(self, poll_id: uuid.UUID) -> int:
        return len([v for v in self._store.votes.values() if v.poll_id == poll_id])

    async def list_open_live_votes_for_user(self, user_id: int) -> list[PollVote]:
        return [v for v in self._store.votes.values() if v.user_id == user_id]


class FakeEnqueteSettingsRepository:
    def __init__(self, session: FakeSession, *, store: PollFakeStore) -> None:
        self._store = store

    async def get_or_create(self, guild_id: int) -> EnqueteSettings:
        settings = self._store.settings.get(guild_id)
        if settings is None:
            settings = EnqueteSettings(guild_id=guild_id, enabled=True, default_weight_mode="SNAPSHOT")
            settings.id = uuid.uuid4()
            self._store.settings[guild_id] = settings
        return settings


class FakeVoteWeightService:
    """Peso fixo pra todo mundo — testes de peso de voto vivem em
    tests/test_vote_weight_service.py; aqui so precisamos de um valor
    previsivel pro PollService orquestrar em torno dele."""

    def __init__(self, weight: int = 1) -> None:
        self.weight = weight

    async def resolve_weight_for_member(self, guild_id: int, member) -> int:
        return self.weight


def install_poll_fakes(monkeypatch, store: PollFakeStore) -> None:
    monkeypatch.setattr(
        "services.poll_service.PollRepository", lambda session: FakePollRepository(session, store=store)
    )
    monkeypatch.setattr(
        "services.poll_service.PollOptionRepository",
        lambda session: FakePollOptionRepository(session, store=store),
    )
    monkeypatch.setattr(
        "services.poll_service.PollVoteRepository", lambda session: FakePollVoteRepository(session, store=store)
    )
    monkeypatch.setattr(
        "services.poll_service.EnqueteSettingsRepository",
        lambda session: FakeEnqueteSettingsRepository(session, store=store),
    )
