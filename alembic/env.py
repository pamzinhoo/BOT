from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from config.settings import get_settings

# Importa todos os modulos de model para popular Base.metadata antes do autogenerate.
from database.models import *  # noqa: F401,F403
from database.models.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata

# O bot e o backend (repo separado `limerence`) compartilham o MESMO banco
# Postgres, mas cada um tem seu proprio historico de migrations Alembic.
# Sem uma version_table dedicada, os dois escrevem na mesma tabela
# `alembic_version` e se sobrescrevem — o proximo `alembic upgrade head` de
# qualquer um dos dois lados acha uma revision que nao existe no seu proprio
# historico e quebra o boot inteiro (CommandError: Can't locate revision).
_VERSION_TABLE = "alembic_version_bot"


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=_VERSION_TABLE,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, version_table=_VERSION_TABLE)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
