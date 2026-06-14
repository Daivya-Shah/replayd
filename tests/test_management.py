import gzip
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from replayd.config import Settings
from replayd.management import create_management_app
from replayd.models import Exchange
from replayd.redaction import REDACTED_VALUE
from replayd.storage.sqlite import SqliteStorage

REQUEST_JSON = b'{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hi"}]}'
RESPONSE_JSON = b'{"id":"resp-1","usage":{"total_tokens":3}}'
GZIP_RESPONSE_JSON = gzip.compress(RESPONSE_JSON)


@pytest.fixture
async def populated_storage(tmp_path: Path) -> AsyncIterator[SqliteStorage]:
    storage = SqliteStorage(str(tmp_path))
    await storage.init()

    started_at = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)
    ended_at = started_at + timedelta(milliseconds=25)

    request_hash = await storage.put_blob(REQUEST_JSON)
    plain_response_hash = await storage.put_blob(RESPONSE_JSON)
    gzip_response_hash = await storage.put_blob(GZIP_RESPONSE_JSON)
    run_id = uuid.uuid4().hex

    await storage.save_exchange(
        Exchange(
            id=uuid.uuid4().hex,
            run_id=run_id,
            created_at=started_at,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=25,
            method="POST",
            path="/v1/chat/completions",
            query=None,
            request_headers={
                "content-type": "application/json",
                "authorization": REDACTED_VALUE,
            },
            request_body_hash=request_hash,
            response_status=200,
            response_headers={"content-type": "application/json"},
            model="gpt-4o-mini",
            usage={"total_tokens": 3},
            provider=None,
            response_body_hash=plain_response_hash,
        )
    )
    await storage.save_exchange(
        Exchange(
            id=uuid.uuid4().hex,
            run_id=run_id,
            created_at=started_at + timedelta(seconds=1),
            started_at=started_at + timedelta(seconds=1),
            ended_at=ended_at + timedelta(seconds=1),
            latency_ms=30,
            method="POST",
            path="/v1/chat/completions",
            query="stream=true",
            request_headers={"content-type": "application/json"},
            request_body_hash=request_hash,
            response_status=200,
            response_headers={
                "content-type": "application/json",
                "content-encoding": "gzip",
            },
            model="gpt-4o-mini",
            usage=None,
            provider=None,
            response_body_hash=gzip_response_hash,
        )
    )

    yield storage
    await storage.aclose()


@pytest.fixture
def management_settings() -> Settings:
    return Settings(
        STORAGE_DIR="./data",
        MGMT_CORS_ORIGIN="http://localhost:3000",
    )


@pytest.mark.asyncio
async def test_list_exchanges_returns_items_total_and_pagination(
    populated_storage: SqliteStorage,
    management_settings: Settings,
) -> None:
    app = create_management_app(settings=management_settings, storage=populated_storage)
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://mgmt") as client:
            response = await client.get("/api/exchanges", params={"limit": 1, "offset": 0})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["limit"] == 1
    assert payload["offset"] == 0
    assert len(payload["items"]) == 1


@pytest.mark.asyncio
async def test_get_exchange_returns_record_and_unknown_id_is_404(
    populated_storage: SqliteStorage,
    management_settings: Settings,
) -> None:
    exchanges = await populated_storage.list_exchanges(limit=1)
    exchange_id = exchanges[0].id
    app = create_management_app(settings=management_settings, storage=populated_storage)
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://mgmt") as client:
            found = await client.get(f"/api/exchanges/{exchange_id}")
            missing = await client.get("/api/exchanges/does-not-exist")

    assert found.status_code == 200
    assert found.json()["id"] == exchange_id
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_get_exchange_response_decodes_gzip_blob(
    populated_storage: SqliteStorage,
    management_settings: Settings,
) -> None:
    exchanges = await populated_storage.list_exchanges()
    gzip_exchange = next(
        exchange
        for exchange in exchanges
        if exchange.response_headers.get("content-encoding") == "gzip"
    )
    app = create_management_app(settings=management_settings, storage=populated_storage)
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://mgmt") as client:
            response = await client.get(f"/api/exchanges/{gzip_exchange.id}/response")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.content == RESPONSE_JSON


@pytest.mark.asyncio
async def test_cors_header_present_on_api_response(
    populated_storage: SqliteStorage,
    management_settings: Settings,
) -> None:
    app = create_management_app(settings=management_settings, storage=populated_storage)
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://mgmt") as client:
            response = await client.get(
                "/api/exchanges",
                headers={"Origin": "http://localhost:3000"},
            )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


@pytest.mark.asyncio
async def test_list_runs_returns_items_and_total(
    populated_storage: SqliteStorage,
    management_settings: Settings,
) -> None:
    app = create_management_app(settings=management_settings, storage=populated_storage)
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://mgmt") as client:
            response = await client.get("/api/runs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["step_count"] == 2


@pytest.mark.asyncio
async def test_get_run_returns_ordered_steps_with_step_index_and_unknown_is_404(
    populated_storage: SqliteStorage,
    management_settings: Settings,
) -> None:
    runs = await populated_storage.list_runs(limit=1)
    run_id = runs[0].run_id
    app = create_management_app(settings=management_settings, storage=populated_storage)
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://mgmt") as client:
            found = await client.get(f"/api/runs/{run_id}")
            missing = await client.get("/api/runs/does-not-exist")

    assert found.status_code == 200
    payload = found.json()
    assert payload["run_id"] == run_id
    assert payload["step_count"] == 2
    assert [step["step_index"] for step in payload["steps"]] == [1, 2]
    assert payload["steps"][0]["started_at"] <= payload["steps"][1]["started_at"]
    assert missing.status_code == 404
