"""Real PostgreSQL checks, restricted to an explicitly named local test database."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.models.redemption import Redemption
from services.redemption_service import RedemptionError, RedemptionService


def _test_url() -> str:
    value = os.environ.get("TEST_REDEMPTION_DATABASE_URL")
    if not value:
        pytest.skip(
            "Set TEST_REDEMPTION_DATABASE_URL to an isolated local PostgreSQL test database."
        )
    parsed = make_url(value)
    if (
        parsed.drivername != "postgresql+asyncpg"
        or parsed.host not in {"127.0.0.1", "localhost", "::1"}
        or not parsed.database
        or not parsed.database.startswith("redemption_test")
    ):
        pytest.fail("Redemption integration tests require a local database named redemption_test*.")
    return value


def _migration(connection, operation: str) -> None:
    path = Path(__file__).resolve().parents[1] / "alembic/versions/b8e4c2d6f019_redemption_codes.py"
    spec = importlib.util.spec_from_file_location("redemption_test_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        getattr(module, operation)()


class _TestDatabase:
    def __init__(self, engine):
        self.engine = engine
        self.factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    @asynccontextmanager
    async def session(self):
        async with self.factory() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise


@pytest.fixture
async def redemption_db():
    url = _test_url()
    schema = "redemption_test_" + uuid.uuid4().hex
    admin = create_async_engine(url)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        url,
        pool_size=10,
        max_overflow=10,
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(lambda sync: _migration(sync, "upgrade"))
        yield _TestDatabase(engine)
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def test_migration_roundtrip_and_database_constraints(redemption_db):
    async with redemption_db.engine.begin() as connection:
        tables = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
        assert set(tables) == {"redemption_codes", "redemptions", "redemption_role_grants"}
        await connection.run_sync(lambda sync: _migration(sync, "downgrade"))
        assert await connection.run_sync(lambda sync: inspect(sync).get_table_names()) == []
        await connection.run_sync(lambda sync: _migration(sync, "upgrade"))
    service = RedemptionService(redemption_db)
    item = await service.create_code(1, code="TEST1234", reward_type="message", message="ok")
    for invalid in ("ABCDEFGH", "12345678", "BAD123!4"):
        with pytest.raises(IntegrityError):
            async with redemption_db.session() as session:
                await session.execute(
                    text("UPDATE redemption_codes SET code=:code WHERE id=:id"),
                    {"code": invalid, "id": uuid.UUID(item["id"])},
                )


async def test_one_hundred_concurrent_users_never_exceed_twenty(redemption_db):
    service = RedemptionService(redemption_db)
    await service.create_code(1, code="TEST1234", reward_type="message", message="ok", max_uses=20)
    outcomes = await asyncio.wait_for(
        asyncio.gather(
            *(
                service._reserve(1, user_id, "TEST1234", member_has_role=False)
                for user_id in range(1, 101)
            ),
            return_exceptions=True,
        ),
        timeout=45,
    )
    successes = [item for item in outcomes if isinstance(item, Redemption)]
    failures = [item for item in outcomes if isinstance(item, Exception)]
    assert len(successes) == 20
    assert len(failures) == 80
    assert all(isinstance(error, RedemptionError) for error in failures)
    async with redemption_db.session() as session:
        assert (
            await session.execute(select(func.count()).select_from(Redemption))
        ).scalar_one() == 20


async def test_concurrent_same_user_keeps_one_reservation_after_restart(redemption_db):
    service = RedemptionService(redemption_db)
    await service.create_code(1, code="TEST1234", reward_type="message", message="ok", max_uses=20)
    outcomes = await asyncio.gather(
        *(service._reserve(1, 999, "TEST1234", member_has_role=False) for _ in range(30))
    )
    assert len({item.id for item in outcomes}) == 1
    restarted = RedemptionService(redemption_db)
    resumed = await restarted._reserve(1, 999, "TEST1234", member_has_role=False)
    assert resumed.id == outcomes[0].id
    async with redemption_db.session() as session:
        assert (
            await session.execute(select(func.count()).select_from(Redemption))
        ).scalar_one() == 1


async def test_server_isolation_validity_and_reward_snapshot(redemption_db):
    service = RedemptionService(redemption_db)
    item = await service.create_code(
        1, code="TEST1234", reward_type="message", message="Original", max_uses=1
    )
    with pytest.raises(RedemptionError):
        await service._reserve(2, 100, "TEST1234", member_has_role=False)
    first = await service._reserve(1, 100, "TEST1234", member_has_role=False)
    await service.update_code(1, uuid.UUID(item["id"]), message="Updated")
    assert first.message == "Original"
    with pytest.raises(RedemptionError):
        await service._reserve(1, 101, "TEST1234", member_has_role=False)
    with pytest.raises(RedemptionError):
        await service.update_code(2, uuid.UUID(item["id"]), active=False)
    with pytest.raises(RedemptionError):
        await service.history(2, uuid.UUID(item["id"]))
    await service.create_code(
        1,
        code="LATE1234",
        reward_type="message",
        message="ok",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    with pytest.raises(RedemptionError):
        await service._reserve(1, 101, "LATE1234", member_has_role=False)


async def test_failure_releases_capacity_without_erasing_user_history(redemption_db):
    service = RedemptionService(redemption_db)
    await service.create_code(1, code="TEST1234", reward_type="message", message="ok", max_uses=1)
    first = await service._reserve(1, 100, "TEST1234", member_has_role=False)
    async with redemption_db.session() as session:
        row = await session.get(Redemption, first.id)
        row.status = "failed"
    second = await service._reserve(1, 101, "TEST1234", member_has_role=False)
    assert second.id != first.id
    repeated = await service._reserve(1, 100, "TEST1234", member_has_role=False)
    assert repeated.id == first.id
    assert repeated.status == "failed"
    async with redemption_db.session() as session:
        assert (
            await session.execute(select(func.count()).select_from(Redemption))
        ).scalar_one() == 2
