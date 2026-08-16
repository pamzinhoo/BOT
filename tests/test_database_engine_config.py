from __future__ import annotations

from database.database import Database


def test_engine_has_pool_recycle_configured() -> None:
    """pool_recycle=1800 — reciclagem proativa das conexoes do pool (defensivo
    contra o pgbouncer do Supabase derrubar conexoes ociosas em silencio).
    pool_pre_ping continua ativo (cobre o caso reativo); os dois nao sao
    mutuamente exclusivos."""
    database = Database("postgresql+asyncpg://user:pass@localhost:5432/db")
    try:
        pool = database.engine.pool
        assert pool._recycle == 1800
        assert pool._pre_ping is True
    finally:
        pool.dispose()
