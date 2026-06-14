"""Programmatic Alembic migration helpers."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine

CORE_TABLES = ("exchanges", "regression_tests", "test_results")
_migration_locks: dict[str, asyncio.Lock] = {}
_migration_locks_guard = asyncio.Lock()


def find_alembic_ini() -> Path:
    migrations_dir = Path(__file__).resolve().parent
    for parent in [Path.cwd(), *migrations_dir.parents]:
        candidate = parent / "alembic.ini"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("alembic.ini not found")


def build_alembic_config(database_url: str) -> Config:
    migrations_dir = Path(__file__).resolve().parent
    config = Config(str(find_alembic_ini()))
    config.set_main_option("script_location", str(migrations_dir))
    os.environ["REPLAYD_DATABASE_URL"] = database_url
    return config


def upgrade_head_sync(database_url: str) -> None:
    command.upgrade(build_alembic_config(database_url), "head")


def upgrade_revision_sync(database_url: str, revision: str) -> None:
    command.upgrade(build_alembic_config(database_url), revision)


def stamp_head_sync(database_url: str) -> None:
    command.stamp(build_alembic_config(database_url), "head")


async def database_has_table(engine: AsyncEngine, table_name: str) -> bool:
    async with engine.connect() as conn:
        return await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).has_table(table_name)
        )


async def database_has_alembic_version(engine: AsyncEngine) -> bool:
    return await database_has_table(engine, "alembic_version")


async def database_has_core_tables(engine: AsyncEngine) -> bool:
    for table_name in CORE_TABLES:
        if not await database_has_table(engine, table_name):
            return False
    return True


async def _migration_lock(database_url: str) -> asyncio.Lock:
    async with _migration_locks_guard:
        lock = _migration_locks.get(database_url)
        if lock is None:
            lock = asyncio.Lock()
            _migration_locks[database_url] = lock
        return lock


async def ensure_schema(
    engine: AsyncEngine,
    database_url: str,
    *,
    run_migrations_on_startup: bool,
) -> None:
    if not run_migrations_on_startup:
        return

    async with await _migration_lock(database_url):
        if await database_has_alembic_version(engine):
            await asyncio.to_thread(upgrade_head_sync, database_url)
            return

        if await database_has_core_tables(engine):
            await asyncio.to_thread(stamp_head_sync, database_url)
            return

        await asyncio.to_thread(upgrade_head_sync, database_url)
