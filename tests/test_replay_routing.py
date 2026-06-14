"""End-to-end replay routing through create_app (not replay_request directly)."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from replayd.config import Settings
from replayd.main import create_app
from replayd.models import Exchange
from replayd.storage.sqlite import SqliteStorage

RUN_ID = "routing-test-run"
REQUEST_BODY = (
    b'{"model":"gpt-4o-mini","messages":[{"role":"user","content":"routing step"}]}'
)
RESPONSE_BODY = b'{"id":"routing-resp","choices":[{"message":{"content":"recorded"}}]}'
RESPONSE_STATUS = 207
REPLAY_HEADER = "x-replayd-replay"


class _ForbiddenUpstreamTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.call_count = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.call_count += 1
        raise AssertionError(
            f"upstream must not be called during replay (method={request.method} url={request.url})"
        )


@pytest.fixture
async def storage_dir_with_run(tmp_path: Path) -> AsyncIterator[Path]:
    storage = SqliteStorage(str(tmp_path))
    await storage.init()

    started_at = datetime(2026, 6, 12, 14, 0, 0, tzinfo=UTC)
    request_hash = await storage.put_blob(REQUEST_BODY)
    response_hash = await storage.put_blob(RESPONSE_BODY)
    await storage.save_exchange(
        Exchange(
            id=uuid.uuid4().hex,
            run_id=RUN_ID,
            created_at=started_at,
            started_at=started_at,
            ended_at=started_at,
            latency_ms=5,
            method="POST",
            path="/v1/chat/completions",
            query=None,
            request_headers={"content-type": "application/json"},
            request_body_hash=request_hash,
            response_status=RESPONSE_STATUS,
            response_headers={"content-type": "application/json"},
            model="gpt-4o-mini",
            usage=None,
            provider=None,
            response_body_hash=response_hash,
        )
    )
    await storage.aclose()
    yield tmp_path


@pytest.mark.asyncio
async def test_proxy_app_replay_header_routes_to_storage_not_upstream(
    storage_dir_with_run: Path,
) -> None:
    upstream_transport = _ForbiddenUpstreamTransport()
    upstream_client = httpx.AsyncClient(
        transport=upstream_transport,
        base_url="http://upstream",
    )
    proxy_app = create_app(
        settings=Settings(
            STORAGE_DIR=str(storage_dir_with_run),
            CAPTURE_ENABLED=True,
            REPLAY_HEADER=REPLAY_HEADER,
        ),
        http_client=upstream_client,
    )
    proxy_transport = httpx.ASGITransport(app=proxy_app)

    async with proxy_app.router.lifespan_context(proxy_app):
        async with httpx.AsyncClient(
            transport=proxy_transport,
            base_url="http://proxy",
        ) as client:
            response = await client.post(
                "/v1/chat/completions",
                content=REQUEST_BODY,
                headers={
                    "Content-Type": "application/json",
                    REPLAY_HEADER: RUN_ID,
                },
            )

    assert upstream_transport.call_count == 0
    assert response.status_code == RESPONSE_STATUS
    assert response.content == RESPONSE_BODY
    await upstream_client.aclose()


@pytest.mark.asyncio
async def test_proxy_app_replay_without_injected_upstream_client(
    storage_dir_with_run: Path,
) -> None:
    """Replay must not use the lifespan upstream client (would fail or hit real API)."""
    proxy_app = create_app(
        settings=Settings(
            STORAGE_DIR=str(storage_dir_with_run),
            CAPTURE_ENABLED=True,
            REPLAY_HEADER=REPLAY_HEADER,
            UPSTREAM_BASE_URL="http://127.0.0.1:59999",
        ),
    )
    proxy_transport = httpx.ASGITransport(app=proxy_app)

    async with proxy_app.router.lifespan_context(proxy_app):
        async with httpx.AsyncClient(
            transport=proxy_transport,
            base_url="http://proxy",
        ) as client:
            response = await client.post(
                "/v1/chat/completions",
                content=REQUEST_BODY,
                headers={
                    "Content-Type": "application/json",
                    REPLAY_HEADER: RUN_ID,
                },
            )

    assert response.status_code == RESPONSE_STATUS
    assert response.content == RESPONSE_BODY


@pytest.mark.asyncio
async def test_proxy_app_replay_header_is_case_insensitive(
    storage_dir_with_run: Path,
) -> None:
    upstream_transport = _ForbiddenUpstreamTransport()
    upstream_client = httpx.AsyncClient(
        transport=upstream_transport,
        base_url="http://upstream",
    )
    proxy_app = create_app(
        settings=Settings(
            STORAGE_DIR=str(storage_dir_with_run),
            CAPTURE_ENABLED=True,
            REPLAY_HEADER=REPLAY_HEADER,
        ),
        http_client=upstream_client,
    )
    proxy_transport = httpx.ASGITransport(app=proxy_app)

    async with proxy_app.router.lifespan_context(proxy_app):
        async with httpx.AsyncClient(
            transport=proxy_transport,
            base_url="http://proxy",
        ) as client:
            response = await client.post(
                "/v1/chat/completions",
                content=REQUEST_BODY,
                headers={
                    "Content-Type": "application/json",
                    "X-Replayd-Replay": RUN_ID,
                },
            )

    assert upstream_transport.call_count == 0
    assert response.status_code == RESPONSE_STATUS
    assert response.content == RESPONSE_BODY
    await upstream_client.aclose()
