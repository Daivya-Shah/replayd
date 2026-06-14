"""Alembic async migration environment."""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from replayd.storage.schema import metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = metadata


def get_database_url() -> str:
    url = os.environ.get("REPLAYD_DATABASE_URL")
    if url:
        return url

    from replayd.config import get_settings
    from replayd.storage.factory import resolve_database_url

    return resolve_database_url(get_settings())


def get_migration_schema() -> str | None:
    return os.environ.get("REPLAYD_MIGRATION_SCHEMA")


def _migration_context_kwargs() -> dict[str, object]:
    kwargs: dict[str, object] = {
        "target_metadata": target_metadata,
        "render_as_batch": True,
    }
    schema = get_migration_schema()
    if schema:
        kwargs["version_table_schema"] = schema
    return kwargs


def _prepare_schema_connection(connection: Connection) -> None:
    schema = get_migration_schema()
    if not schema:
        return
    from sqlalchemy import text

    connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
    connection.execute(text(f'SET search_path TO "{schema}"'))


def run_migrations_offline() -> None:
    url = get_database_url()
    context.configure(
        url=url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_migration_context_kwargs(),
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    _prepare_schema_connection(connection)
    context.configure(
        connection=connection,
        **_migration_context_kwargs(),
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_database_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
