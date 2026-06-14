import logging
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from replayd.config import Settings
from replayd.management import create_management_app
from replayd.storage.sqlite import SqliteStorage

API_TOKEN = "test-control-plane-token"


@pytest.fixture
async def storage(tmp_path: Path) -> AsyncIterator[SqliteStorage]:
    store = SqliteStorage(str(tmp_path))
    await store.init()
    yield store
    await store.aclose()


def _management_client(
    storage: SqliteStorage,
    settings: Settings,
) -> tuple[httpx.AsyncClient, object]:
    app = create_management_app(settings=settings, storage=storage)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://mgmt"), app


@pytest.mark.asyncio
async def test_health_works_without_token_when_auth_enabled(
    storage: SqliteStorage,
    tmp_path: Path,
) -> None:
    settings = Settings(
        STORAGE_DIR=str(tmp_path),
        REPLAYD_API_TOKEN=API_TOKEN,
    )
    client, app = _management_client(storage, settings)

    async with app.router.lifespan_context(app):
        async with client:
            response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_api_runs_requires_token_when_auth_enabled(
    storage: SqliteStorage,
    tmp_path: Path,
) -> None:
    settings = Settings(
        STORAGE_DIR=str(tmp_path),
        REPLAYD_API_TOKEN=API_TOKEN,
    )
    client, app = _management_client(storage, settings)

    async with app.router.lifespan_context(app):
        async with client:
            missing = await client.get("/api/runs")
            wrong = await client.get(
                "/api/runs",
                headers={"Authorization": "Bearer wrong-token"},
            )
            ok = await client.get(
                "/api/runs",
                headers={"Authorization": f"Bearer {API_TOKEN}"},
            )
            header_ok = await client.get(
                "/api/runs",
                headers={"X-Replayd-Token": API_TOKEN},
            )

    assert missing.status_code == 401
    assert missing.json() == {"error": "unauthorized"}
    assert wrong.status_code == 401
    assert wrong.json() == {"error": "unauthorized"}
    assert ok.status_code == 200
    assert header_ok.status_code == 200


@pytest.mark.asyncio
async def test_api_runs_works_without_token_in_dev_mode(
    storage: SqliteStorage,
    tmp_path: Path,
) -> None:
    settings = Settings(
        STORAGE_DIR=str(tmp_path),
        REPLAYD_API_TOKEN=None,
    )
    client, app = _management_client(storage, settings)

    async with app.router.lifespan_context(app):
        async with client:
            response = await client.get("/api/runs")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_dev_mode_logs_unprotected_warning(
    storage: SqliteStorage,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = Settings(
        STORAGE_DIR=str(tmp_path),
        REPLAYD_API_TOKEN=None,
    )
    app = create_management_app(settings=settings, storage=storage)

    with caplog.at_level(logging.WARNING):
        async with app.router.lifespan_context(app):
            pass

    assert any(
        "unprotected" in record.message.lower()
        for record in caplog.records
    )
