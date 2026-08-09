from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.logger import get_logger

logger = get_logger("database")


class Database:
    """Ponto unico de acesso ao engine e as sessoes assincronas do banco."""

    def __init__(
        self,
        database_url: str,
        *,
        echo: bool = False,
        pool_size: int = 10,
        max_overflow: int = 20,
    ) -> None:
        self._engine: AsyncEngine = create_async_engine(
            database_url,
            echo=echo,
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
            connect_args={"statement_cache_size": 0},
        )
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            expire_on_commit=False,
            autoflush=False,
        )

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    async def check_connection(self) -> None:
        async with self._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Conexao com o banco de dados verificada com sucesso.")

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        session = self._session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def close(self) -> None:
        await self._engine.dispose()
        logger.info("Conexoes do banco de dados encerradas.")


_database: Database | None = None


def init_database(
    database_url: str, *, echo: bool = False, pool_size: int = 10, max_overflow: int = 20
) -> Database:
    global _database
    _database = Database(database_url, echo=echo, pool_size=pool_size, max_overflow=max_overflow)
    return _database


def get_database() -> Database:
    if _database is None:
        raise RuntimeError("Database ainda nao foi inicializado. Chame init_database() primeiro.")
    return _database
