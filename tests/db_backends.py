"""Test helpers for SQLite and optional Postgres backends."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from replayd.storage.base import Storage
from replayd.storage.sql import SqlStorage
from replayd.storage.sqlite import SqliteStorage

POSTGRES_TEST_URL = os.environ.get("REPLAYD_TEST_DATABASE_URL")
_POSTGRES_MAINTENANCE_DB = "postgres"


def postgres_testing_enabled() -> bool:
    return POSTGRES_TEST_URL is not None


def dual_params() -> list[pytest.ParameterSet]:
    params: list[pytest.ParameterSet] = [pytest.param("sqlite", id="sqlite")]
    if postgres_testing_enabled():
        params.append(pytest.param("postgres", id="postgres"))
    return params


def _require_postgres_test_url() -> str:
    if POSTGRES_TEST_URL is None:
        raise RuntimeError("REPLAYD_TEST_DATABASE_URL is not set")
    return POSTGRES_TEST_URL


def postgres_maintenance_url() -> str:
    """Server URL for CREATE/DROP DATABASE (connects to the maintenance database)."""
    return make_url(_require_postgres_test_url()).set(
        database=_POSTGRES_MAINTENANCE_DB
    ).render_as_string(hide_password=False)


def postgres_database_url(database_name: str) -> str:
    return make_url(_require_postgres_test_url()).set(
        database=database_name
    ).render_as_string(hide_password=False)


def _new_postgres_database_name() -> str:
    return f"test_{uuid.uuid4().hex}"


async def create_postgres_test_database() -> tuple[str, str]:
    """Create an empty per-test database. Returns (database_name, database_url)."""
    database_name = _new_postgres_database_name()
    maintenance_engine = create_async_engine(
        postgres_maintenance_url(),
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with maintenance_engine.connect() as conn:
            await conn.execute(
                text(f'CREATE DATABASE "{database_name}"')
            )
    finally:
        await maintenance_engine.dispose()

    return database_name, postgres_database_url(database_name)


async def drop_postgres_test_database(database_name: str) -> None:
    maintenance_engine = create_async_engine(
        postgres_maintenance_url(),
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with maintenance_engine.connect() as conn:
            await conn.execute(
                text(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = :database_name
                      AND pid <> pg_backend_pid()
                    """
                ),
                {"database_name": database_name},
            )
            await conn.execute(
                text(f'DROP DATABASE IF EXISTS "{database_name}"')
            )
    finally:
        await maintenance_engine.dispose()


async def postgres_table_names(database_url: str) -> set[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_type = 'BASE TABLE'
                    """
                )
            )
            return {row[0] for row in result}
    finally:
        await engine.dispose()


async def postgres_column_names(database_url: str, table_name: str) -> set[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = :table_name
                    """
                ),
                {"table_name": table_name},
            )
            return {row[0] for row in result}
    finally:
        await engine.dispose()


async def postgres_index_names(database_url: str, table_name: str) -> set[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = 'public' AND tablename = :table_name
                    """
                ),
                {"table_name": table_name},
            )
            return {row[0] for row in result}
    finally:
        await engine.dispose()


async def create_postgres_test_storage(blob_dir: Path) -> tuple[SqlStorage, str]:
    database_name, database_url = await create_postgres_test_database()
    storage = SqlStorage(
        database_url=database_url,
        storage_dir=str(blob_dir),
    )
    await storage.init()
    return storage, database_name


async def open_test_storage(
    backend: str,
    tmp_path: Path,
) -> tuple[Storage, str | None]:
    if backend == "sqlite":
        storage = SqliteStorage(str(tmp_path))
        await storage.init()
        return storage, None
    storage, database_name = await create_postgres_test_storage(tmp_path)
    return storage, database_name


async def close_test_storage(
    storage: Storage,
    backend: str,
    database_name: str | None,
) -> None:
    await storage.aclose()
    if backend == "postgres" and database_name is not None:
        await drop_postgres_test_database(database_name)
