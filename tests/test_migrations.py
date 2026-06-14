"""Alembic migration tests."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import aiosqlite
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from replayd.migrations.runner import upgrade_head_sync, upgrade_revision_sync
from replayd.tenancy import (
    DEFAULT_ORG_ID,
    DEFAULT_ORG_SLUG,
    DEFAULT_PROJECT_ID,
    DEFAULT_PROJECT_SLUG,
)
from replayd.storage.sql import list_table_names
from replayd.storage.sqlite import SqliteStorage
from db_backends import (
    create_postgres_test_database,
    drop_postgres_test_database,
    dual_params,
    postgres_column_names,
    postgres_index_names,
    postgres_table_names,
)

EXPECTED_INDEXES = {
    "exchanges": {"idx_exchanges_created_at", "idx_exchanges_run_id"},
    "test_results": {"idx_test_results_test_id_run_at"},
}

EXPECTED_EXCHANGE_COLUMNS = {
    "id",
    "project_id",
    "run_id",
    "parent_run_id",
    "origin",
    "created_at",
    "started_at",
    "ended_at",
    "latency_ms",
    "method",
    "path",
    "query",
    "request_headers",
    "request_body_hash",
    "response_status",
    "response_headers",
    "model",
    "usage",
    "provider",
    "response_body_hash",
}

EXPECTED_REGRESSION_TEST_COLUMNS = {
    "id",
    "project_id",
    "name",
    "baseline_run_id",
    "created_at",
    "mode",
}

EXPECTED_TEST_RESULT_COLUMNS = {
    "id",
    "test_id",
    "run_at",
    "status",
    "total_steps",
    "matched_steps",
    "first_divergent_step_index",
    "detail",
    "candidate_run_id",
    "step_diffs",
}


def _sqlite_database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


async def _sqlite_index_names(path: Path, table_name: str) -> set[str]:
    async with aiosqlite.connect(path) as conn:
        cursor = await conn.execute(f"PRAGMA index_list({table_name})")
        rows = await cursor.fetchall()
    return {
        row[1]
        for row in rows
        if not row[1].startswith("sqlite_autoindex_")
    }


async def _sqlite_column_names(path: Path, table_name: str) -> set[str]:
    async with aiosqlite.connect(path) as conn:
        cursor = await conn.execute(f"PRAGMA table_info({table_name})")
        rows = await cursor.fetchall()
    return {row[1] for row in rows}


def _assert_application_indexes_present(
    actual_indexes: set[str],
    table_name: str,
) -> None:
    expected = EXPECTED_INDEXES[table_name]
    missing = expected - actual_indexes
    assert not missing, (
        f"missing application indexes on {table_name}: {sorted(missing)} "
        f"(actual: {sorted(actual_indexes)})"
    )


async def _create_pre_alembic_schema(db_path: Path) -> None:
    """Create the full schema as it existed before Alembic versioning was introduced."""
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            """
            CREATE TABLE organizations (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE projects (
                id TEXT PRIMARY KEY,
                org_id TEXT NOT NULL,
                name TEXT NOT NULL,
                slug TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(org_id) REFERENCES organizations (id),
                UNIQUE (org_id, slug)
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE exchanges (
                id TEXT PRIMARY KEY,
                project_id TEXT,
                run_id TEXT NOT NULL,
                parent_run_id TEXT,
                origin TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT NOT NULL,
                latency_ms INTEGER NOT NULL,
                method TEXT NOT NULL,
                path TEXT NOT NULL,
                query TEXT,
                request_headers TEXT NOT NULL,
                request_body_hash TEXT,
                response_status INTEGER NOT NULL,
                response_headers TEXT NOT NULL,
                model TEXT,
                usage TEXT,
                provider TEXT,
                response_body_hash TEXT,
                FOREIGN KEY(project_id) REFERENCES projects (id)
            )
            """
        )
        await conn.execute(
            "CREATE INDEX idx_exchanges_created_at ON exchanges (created_at)"
        )
        await conn.execute("CREATE INDEX idx_exchanges_run_id ON exchanges (run_id)")
        await conn.execute(
            "CREATE INDEX idx_exchanges_project_id ON exchanges (project_id)"
        )
        await conn.execute(
            """
            CREATE TABLE regression_tests (
                id TEXT PRIMARY KEY,
                project_id TEXT,
                name TEXT NOT NULL,
                baseline_run_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'exact',
                FOREIGN KEY(project_id) REFERENCES projects (id)
            )
            """
        )
        await conn.execute(
            """
            CREATE INDEX idx_regression_tests_project_id
            ON regression_tests (project_id)
            """
        )
        await conn.execute(
            """
            CREATE TABLE test_results (
                id TEXT PRIMARY KEY,
                test_id TEXT NOT NULL,
                run_at TEXT NOT NULL,
                status TEXT NOT NULL,
                total_steps INTEGER NOT NULL,
                matched_steps INTEGER NOT NULL,
                first_divergent_step_index INTEGER,
                detail TEXT NOT NULL,
                candidate_run_id TEXT,
                step_diffs TEXT NOT NULL DEFAULT '[]',
                FOREIGN KEY(test_id) REFERENCES regression_tests (id)
            )
            """
        )
        await conn.execute(
            """
            CREATE INDEX idx_test_results_test_id_run_at
            ON test_results (test_id, run_at)
            """
        )
        await conn.execute(
            """
            INSERT INTO organizations (id, name, slug, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (DEFAULT_ORG_ID, "Default Organization", DEFAULT_ORG_SLUG, "2026-06-13T00:00:00+00:00"),
        )
        await conn.execute(
            """
            INSERT INTO projects (id, org_id, name, slug, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                DEFAULT_PROJECT_ID,
                DEFAULT_ORG_ID,
                "Default Project",
                DEFAULT_PROJECT_SLUG,
                "2026-06-13T00:00:00+00:00",
            ),
        )
        await conn.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("db_backend", dual_params())
async def test_upgrade_empty_db_creates_expected_schema(
    tmp_path: Path,
    db_backend: str,
) -> None:
    if db_backend == "sqlite":
        db_path = tmp_path / "replayd.db"
        database_url = _sqlite_database_url(db_path)
        await asyncio.to_thread(upgrade_head_sync, database_url)

        tables = await list_table_names(create_async_engine(database_url))
        assert "exchanges" in tables
        assert "regression_tests" in tables
        assert "test_results" in tables
        assert "alembic_version" in tables

        assert (
            await _sqlite_column_names(db_path, "exchanges") == EXPECTED_EXCHANGE_COLUMNS
        )
        assert (
            await _sqlite_column_names(db_path, "regression_tests")
            == EXPECTED_REGRESSION_TEST_COLUMNS
        )
        assert (
            await _sqlite_column_names(db_path, "test_results")
            == EXPECTED_TEST_RESULT_COLUMNS
        )

        _assert_application_indexes_present(
            await _sqlite_index_names(db_path, "exchanges"),
            "exchanges",
        )
        _assert_application_indexes_present(
            await _sqlite_index_names(db_path, "test_results"),
            "test_results",
        )
        return

    database_name, database_url = await create_postgres_test_database()
    try:
        await asyncio.to_thread(upgrade_head_sync, database_url)
        tables = await postgres_table_names(database_url)

        assert "exchanges" in tables
        assert "regression_tests" in tables
        assert "test_results" in tables
        assert "alembic_version" in tables

        assert (
            await postgres_column_names(database_url, "exchanges")
            == EXPECTED_EXCHANGE_COLUMNS
        )
        assert (
            await postgres_column_names(database_url, "regression_tests")
            == EXPECTED_REGRESSION_TEST_COLUMNS
        )
        assert (
            await postgres_column_names(database_url, "test_results")
            == EXPECTED_TEST_RESULT_COLUMNS
        )

        _assert_application_indexes_present(
            await postgres_index_names(database_url, "exchanges"),
            "exchanges",
        )
        _assert_application_indexes_present(
            await postgres_index_names(database_url, "test_results"),
            "test_results",
        )
    finally:
        await drop_postgres_test_database(database_name)


@pytest.mark.asyncio
@pytest.mark.parametrize("db_backend", dual_params())
async def test_upgrade_head_twice_is_idempotent(
    tmp_path: Path,
    db_backend: str,
) -> None:
    if db_backend == "sqlite":
        database_url = _sqlite_database_url(tmp_path / "replayd.db")
        await asyncio.to_thread(upgrade_head_sync, database_url)
        await asyncio.to_thread(upgrade_head_sync, database_url)
        return

    database_name, database_url = await create_postgres_test_database()
    try:
        await asyncio.to_thread(upgrade_head_sync, database_url)
        await asyncio.to_thread(upgrade_head_sync, database_url)
    finally:
        await drop_postgres_test_database(database_name)


@pytest.mark.asyncio
async def test_init_stamps_pre_alembic_database_with_core_tables(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "replayd.db"
    (tmp_path / "blobs").mkdir()
    exchange_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    started_at = "2026-06-12T10:00:00+00:00"
    ended_at = "2026-06-12T10:00:00.042000+00:00"

    await _create_pre_alembic_schema(db_path)

    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            """
            INSERT INTO exchanges (
                id, run_id, created_at, started_at, ended_at, latency_ms, method,
                path, query, request_headers, request_body_hash, response_status,
                response_headers, model, usage, provider, response_body_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                exchange_id,
                run_id,
                started_at,
                started_at,
                ended_at,
                42,
                "POST",
                "/v1/chat/completions",
                None,
                '{"content-type": "application/json"}',
                None,
                200,
                '{"content-type": "application/json"}',
                "gpt-4o-mini",
                None,
                None,
                None,
            ),
        )
        await conn.commit()

    storage = SqliteStorage(str(tmp_path))
    await storage.init()
    try:
        assert storage._engine is not None
        async with storage._engine.connect() as conn:
            version = await conn.scalar(text("SELECT version_num FROM alembic_version"))
        assert version == "0003"

        exchange = await storage.get_exchange(exchange_id)
        assert exchange is not None
        assert exchange.run_id == run_id
    finally:
        await storage.aclose()


async def _insert_legacy_exchange_at_0001(db_path: Path) -> str:
    exchange_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    started_at = "2026-06-12T10:00:00+00:00"
    ended_at = "2026-06-12T10:00:00.042000+00:00"
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            """
            INSERT INTO exchanges (
                id, run_id, created_at, started_at, ended_at, latency_ms, method,
                path, query, request_headers, request_body_hash, response_status,
                response_headers, model, usage, provider, response_body_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                exchange_id,
                run_id,
                started_at,
                started_at,
                ended_at,
                42,
                "POST",
                "/v1/chat/completions",
                None,
                '{"content-type": "application/json"}',
                None,
                200,
                '{"content-type": "application/json"}',
                "gpt-4o-mini",
                None,
                None,
                None,
            ),
        )
        await conn.commit()
    return exchange_id


@pytest.mark.asyncio
@pytest.mark.parametrize("db_backend", dual_params())
async def test_migration_0002_backfills_default_project_from_0001_baseline(
    tmp_path: Path,
    db_backend: str,
) -> None:
    if db_backend == "sqlite":
        db_path = tmp_path / "replayd.db"
        database_url = _sqlite_database_url(db_path)
        await asyncio.to_thread(upgrade_revision_sync, database_url, "0001")
        exchange_id = await _insert_legacy_exchange_at_0001(db_path)
        await asyncio.to_thread(upgrade_head_sync, database_url)

        async with aiosqlite.connect(db_path) as conn:
            cursor = await conn.execute(
                "SELECT project_id FROM exchanges WHERE id = ?",
                (exchange_id,),
            )
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == DEFAULT_PROJECT_ID

            cursor = await conn.execute(
                "SELECT id, slug FROM organizations WHERE id = ?",
                (DEFAULT_ORG_ID,),
            )
            org_row = await cursor.fetchone()
            assert org_row is not None
            assert org_row[1] == DEFAULT_ORG_SLUG

            cursor = await conn.execute(
                "SELECT id, slug FROM projects WHERE id = ?",
                (DEFAULT_PROJECT_ID,),
            )
            project_row = await cursor.fetchone()
            assert project_row is not None
            assert project_row[1] == DEFAULT_PROJECT_SLUG
        return

    database_name, database_url = await create_postgres_test_database()
    try:
        await asyncio.to_thread(upgrade_revision_sync, database_url, "0001")
        engine = create_async_engine(database_url)
        exchange_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        started_at = "2026-06-12T10:00:00+00:00"
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO exchanges (
                        id, run_id, created_at, started_at, ended_at, latency_ms,
                        method, path, query, request_headers, request_body_hash,
                        response_status, response_headers, model, usage, provider,
                        response_body_hash
                    ) VALUES (
                        :id, :run_id, :created_at, :started_at, :ended_at, 42,
                        'POST', '/v1/chat/completions', NULL, '{}', NULL,
                        200, '{}', NULL, NULL, NULL, NULL
                    )
                    """
                ),
                {
                    "id": exchange_id,
                    "run_id": run_id,
                    "created_at": started_at,
                    "started_at": started_at,
                    "ended_at": started_at,
                },
            )
        await engine.dispose()

        await asyncio.to_thread(upgrade_head_sync, database_url)

        engine = create_async_engine(database_url)
        async with engine.connect() as conn:
            project_id = await conn.scalar(
                text("SELECT project_id FROM exchanges WHERE id = :id"),
                {"id": exchange_id},
            )
            assert project_id == DEFAULT_PROJECT_ID

            org_slug = await conn.scalar(
                text("SELECT slug FROM organizations WHERE id = :id"),
                {"id": DEFAULT_ORG_ID},
            )
            assert org_slug == DEFAULT_ORG_SLUG

            project_slug = await conn.scalar(
                text("SELECT slug FROM projects WHERE id = :id"),
                {"id": DEFAULT_PROJECT_ID},
            )
            assert project_slug == DEFAULT_PROJECT_SLUG
        await engine.dispose()
    finally:
        await drop_postgres_test_database(database_name)
