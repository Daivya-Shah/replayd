import asyncio
import hashlib
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiosqlite
import pytest

from replayd.models import Exchange
from replayd.redaction import REDACTED_VALUE, redact_headers
from replayd.storage.base import Storage
from replayd.storage.sql import SqlStorage, list_table_names
from replayd.storage.sqlite import SqliteStorage
from replayd.tenancy import DEFAULT_PROJECT_ID
from db_backends import close_test_storage, dual_params, open_test_storage

MOCK_AUTH = "Bearer test-secret-key"
REQUEST_BODY = b'{"model":"gpt-4o","messages":[{"role":"user","content":"hi"}]}'
RESPONSE_BODY = b'{"id":"resp-1","object":"chat.completion"}'


@pytest.fixture
async def sqlite_storage(tmp_path: Path) -> AsyncIterator[SqliteStorage]:
    store = SqliteStorage(str(tmp_path))
    await store.init()
    yield store
    await store.aclose()


def _sample_exchange(
    *,
    exchange_id: str | None = None,
    run_id: str | None = None,
    project_id: str | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    latency_ms: int = 42,
    response_status: int = 200,
    model: str | None = "gpt-4o-mini",
    request_headers: dict[str, str] | None = None,
    request_body_hash: str | None = "abc123",
    response_body_hash: str | None = "def456",
) -> Exchange:
    exchange_id = exchange_id or uuid.uuid4().hex
    base_started = started_at or datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)
    base_ended = ended_at or base_started + timedelta(milliseconds=latency_ms)
    return Exchange(
        id=exchange_id,
        run_id=run_id or exchange_id,
        project_id=project_id,
        created_at=base_started,
        started_at=base_started,
        ended_at=base_ended,
        latency_ms=latency_ms,
        method="POST",
        path="/v1/chat/completions",
        query="stream=false",
        request_headers=request_headers
        or {
            "content-type": "application/json",
            "authorization": REDACTED_VALUE,
        },
        request_body_hash=request_body_hash,
        response_status=response_status,
        response_headers={"content-type": "application/json"},
        model=model,
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        provider="openai",
        response_body_hash=response_body_hash,
    )


def _blob_file_count(storage_dir: Path) -> int:
    blob_dir = storage_dir / "blobs"
    if not blob_dir.exists():
        return 0
    return sum(1 for path in blob_dir.rglob("*") if path.is_file())


@pytest.mark.asyncio
async def test_put_blob_returns_sha256_and_round_trips(
    core_storage: Storage,
    tmp_path: Path,
) -> None:
    digest = await core_storage.put_blob(REQUEST_BODY)

    assert digest == hashlib.sha256(REQUEST_BODY).hexdigest()
    assert await core_storage.get_blob(digest) == REQUEST_BODY
    assert _blob_file_count(tmp_path) == 1


@pytest.mark.asyncio
async def test_put_blob_dedupes_identical_bytes(
    core_storage: Storage,
    tmp_path: Path,
) -> None:
    first_digest = await core_storage.put_blob(REQUEST_BODY)
    second_digest = await core_storage.put_blob(REQUEST_BODY)

    assert first_digest == second_digest
    assert _blob_file_count(tmp_path) == 1


@pytest.mark.asyncio
async def test_save_exchange_get_exchange_and_list_round_trip(
    core_storage: Storage,
) -> None:
    exchange = _sample_exchange()
    await core_storage.save_exchange(exchange)

    loaded = await core_storage.get_exchange(exchange.id)
    assert loaded == exchange.model_copy(update={"project_id": DEFAULT_PROJECT_ID})

    listed = await core_storage.list_exchanges()
    assert len(listed) == 1
    assert listed[0] == exchange.model_copy(update={"project_id": DEFAULT_PROJECT_ID})


@pytest.mark.asyncio
async def test_redaction_never_persists_authorization_token(
    sqlite_storage: SqliteStorage,
    tmp_path: Path,
) -> None:
    redacted_headers = redact_headers(
        {
            "Authorization": MOCK_AUTH,
            "Content-Type": "application/json",
        }
    )
    exchange = _sample_exchange(request_headers=redacted_headers)
    await sqlite_storage.save_exchange(exchange)

    loaded = await sqlite_storage.get_exchange(exchange.id)
    assert loaded is not None
    auth_header = next(
        value
        for key, value in loaded.request_headers.items()
        if key.lower() == "authorization"
    )
    assert auth_header == REDACTED_VALUE
    assert MOCK_AUTH not in loaded.request_headers.values()

    db_path = tmp_path / "replayd.db"
    async with aiosqlite.connect(db_path) as conn:
        cursor = await conn.execute(
            "SELECT request_headers FROM exchanges WHERE id = ?",
            (exchange.id,),
        )
        row = await cursor.fetchone()
    assert row is not None
    stored_json = row[0]
    assert MOCK_AUTH not in stored_json
    assert REDACTED_VALUE in json.loads(stored_json).values()


@pytest.mark.asyncio
async def test_list_runs_groups_exchanges_and_aggregates_metrics(
    core_storage: Storage,
) -> None:
    run_id = "shared-run-id"
    first_started = datetime(2026, 6, 12, 10, 0, 0, tzinfo=UTC)
    second_started = first_started + timedelta(seconds=1)
    third_started = first_started + timedelta(seconds=2)

    await core_storage.save_exchange(
        _sample_exchange(
            run_id=run_id,
            started_at=first_started,
            latency_ms=10,
            response_status=200,
        )
    )
    await core_storage.save_exchange(
        _sample_exchange(
            run_id=run_id,
            started_at=second_started,
            latency_ms=20,
            response_status=201,
        )
    )
    await core_storage.save_exchange(
        _sample_exchange(
            run_id=run_id,
            started_at=third_started,
            latency_ms=30,
            response_status=500,
            model="gpt-4o",
        )
    )

    runs = await core_storage.list_runs()
    assert len(runs) == 1
    run = runs[0]
    assert run.run_id == run_id
    assert run.step_count == 3
    assert run.started_at == first_started
    assert run.ended_at == third_started + timedelta(milliseconds=30)
    assert run.total_latency_ms == 60
    assert run.models == ["gpt-4o", "gpt-4o-mini"]
    assert run.final_status == 500

    steps = await core_storage.get_run(run_id)
    assert len(steps) == 3
    assert [step.started_at for step in steps] == sorted(
        [first_started, second_started, third_started]
    )


@pytest.mark.asyncio
async def test_concurrent_init_on_same_database_path(tmp_path: Path) -> None:
    storage_dir = str(tmp_path)
    storage_a = SqliteStorage(storage_dir)
    storage_b = SqliteStorage(storage_dir)

    await asyncio.gather(storage_a.init(), storage_b.init())

    try:
        async with aiosqlite.connect(tmp_path / "replayd.db") as conn:
            cursor = await conn.execute("PRAGMA journal_mode")
            row = await cursor.fetchone()
        assert row is not None
        assert row[0].lower() == "wal"

        payload = b"concurrent-init-test"
        digest = await storage_a.put_blob(payload)
        assert await storage_b.get_blob(digest) == payload
    finally:
        await storage_a.aclose()
        await storage_b.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("db_backend", dual_params())
async def test_sql_storage_init_creates_tables_and_round_trips(
    tmp_path: Path,
    db_backend: str,
) -> None:
    storage, schema = await open_test_storage(db_backend, tmp_path)
    try:
        assert isinstance(storage, SqlStorage)
        assert storage._engine is not None

        tables = await list_table_names(storage._engine)
        assert "exchanges" in tables
        assert "regression_tests" in tables
        assert "test_results" in tables

        digest = await storage.put_blob(REQUEST_BODY)
        assert await storage.get_blob(digest) == REQUEST_BODY

        exchange = _sample_exchange(
            request_body_hash=digest,
            response_body_hash=digest,
        )
        await storage.save_exchange(exchange)
        loaded = await storage.get_exchange(exchange.id)
        assert loaded == exchange.model_copy(update={"project_id": DEFAULT_PROJECT_ID})
    finally:
        await close_test_storage(storage, db_backend, schema)
