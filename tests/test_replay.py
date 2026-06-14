import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import Request
from starlette.responses import Response

from replayd.config import Settings
from replayd.main import create_app
from replayd.models import Exchange
from replayd.proxy import replay_request
from replayd.storage.base import Storage
from replayd.storage.sqlite import SqliteStorage
from db_backends import close_test_storage, dual_params, open_test_storage

RUN_ID = "replay-test-run"
REQUEST_BODIES = [
    b'{"model":"gpt-4o-mini","messages":[{"role":"user","content":"step 1"}]}',
    b'{"model":"gpt-4o-mini","messages":[{"role":"user","content":"step 2"}]}',
    b'{"model":"gpt-4o-mini","messages":[{"role":"user","content":"step 3"}]}',
]
RESPONSE_BODIES = [
    b'{"id":"resp-1","choices":[{"message":{"content":"reply 1"}}]}',
    b'{"id":"resp-2","choices":[{"message":{"content":"reply 2"}}]}',
    b'{"id":"resp-3","choices":[{"message":{"content":"reply 3"}}]}',
]
RESPONSE_STATUSES = [200, 201, 202]
REPLAY_HEADER = "x-replayd-replay"


@pytest.fixture
def settings() -> Settings:
    return Settings(REPLAY_HEADER=REPLAY_HEADER)


@pytest.fixture(params=dual_params())
async def populated_run(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> AsyncIterator[Storage]:
    backend: str = request.param
    storage, schema = await open_test_storage(backend, tmp_path)

    started_at = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)

    for index, (request_body, response_body, status) in enumerate(
        zip(REQUEST_BODIES, RESPONSE_BODIES, RESPONSE_STATUSES, strict=True),
    ):
        step_started = started_at + timedelta(seconds=index)
        step_ended = step_started + timedelta(milliseconds=10)
        request_hash = await storage.put_blob(request_body)
        response_hash = await storage.put_blob(response_body)

        await storage.save_exchange(
            Exchange(
                id=uuid.uuid4().hex,
                run_id=RUN_ID,
                created_at=step_started,
                started_at=step_started,
                ended_at=step_ended,
                latency_ms=10,
                method="POST",
                path="/v1/chat/completions",
                query=None,
                request_headers={"content-type": "application/json"},
                request_body_hash=request_hash,
                response_status=status,
                response_headers={"content-type": "application/json"},
                model="gpt-4o-mini",
                usage={"total_tokens": 3},
                provider=None,
                response_body_hash=response_hash,
            )
        )

    try:
        yield storage
    finally:
        await close_test_storage(storage, backend, schema)


async def _receive(body: bytes) -> dict[str, object]:
    return {"type": "http.request", "body": body, "more_body": False}


def _request_scope(body: bytes, *, run_id: str) -> dict[str, object]:
    return {
        "type": "http",
        "asgi": {"spec_version": "2.3", "version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/chat/completions",
        "raw_path": b"/v1/chat/completions",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (REPLAY_HEADER.encode(), run_id.encode()),
            (b"content-type", b"application/json"),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("proxy", 80),
        "state": {},
    }


async def _response_body(response: Response) -> bytes:
    if hasattr(response, "body") and response.body:
        return response.body
    chunks: list[bytes] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)


@pytest.mark.asyncio
async def test_replay_match_returns_recorded_step_response(
    populated_run: Storage,
    settings: Settings,
) -> None:
    scope = _request_scope(REQUEST_BODIES[1], run_id=RUN_ID)
    request = Request(scope, lambda: _receive(REQUEST_BODIES[1]))

    response = await replay_request(request, populated_run, settings)

    assert response.status_code == RESPONSE_STATUSES[1]
    assert await _response_body(response) == RESPONSE_BODIES[1]


@pytest.mark.asyncio
async def test_replay_divergence_when_body_does_not_match(
    populated_run: Storage,
    settings: Settings,
) -> None:
    unknown_body = b'{"model":"gpt-4o-mini","messages":[{"role":"user","content":"unknown"}]}'
    scope = _request_scope(unknown_body, run_id=RUN_ID)
    request = Request(scope, lambda: _receive(unknown_body))

    response = await replay_request(request, populated_run, settings)
    payload = json.loads(await _response_body(response))

    assert response.status_code == 422
    assert payload["error"] == "replay_divergence"
    assert payload["run_id"] == RUN_ID
    assert payload["request_body_hash"] is not None


@pytest.mark.asyncio
async def test_replay_does_not_capture_new_exchange(
    populated_run: Storage,
    settings: Settings,
) -> None:
    before = await populated_run.count_exchanges()
    scope = _request_scope(REQUEST_BODIES[0], run_id=RUN_ID)
    request = Request(scope, lambda: _receive(REQUEST_BODIES[0]))

    response = await replay_request(request, populated_run, settings)
    assert response.status_code == RESPONSE_STATUSES[0]
    assert await populated_run.count_exchanges() == before


@pytest.mark.asyncio
async def test_replay_unknown_run_returns_404(settings: Settings, tmp_path: Path) -> None:
    storage = SqliteStorage(str(tmp_path))
    await storage.init()
    try:
        scope = _request_scope(REQUEST_BODIES[0], run_id="missing-run")
        request = Request(scope, lambda: _receive(REQUEST_BODIES[0]))

        response = await replay_request(request, storage, settings)
        payload = json.loads(await _response_body(response))

        assert response.status_code == 404
        assert payload == {"error": "run_not_found", "run_id": "missing-run"}
    finally:
        await storage.aclose()


@pytest.mark.asyncio
async def test_replay_routing_skips_upstream_client(
    populated_run: Storage,
) -> None:
    async def _forbidden_upstream_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("upstream must not be called during replay")

    upstream_client = httpx.AsyncClient(
        transport=httpx.MockTransport(_forbidden_upstream_handler),
        base_url="http://upstream",
    )
    proxy_app = create_app(
        settings=Settings(UPSTREAM_BASE_URL="http://upstream"),
        http_client=upstream_client,
        storage=populated_run,
    )
    transport = httpx.ASGITransport(app=proxy_app)

    async with proxy_app.router.lifespan_context(proxy_app):
        async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
            response = await client.post(
                "/v1/chat/completions",
                content=REQUEST_BODIES[1],
                headers={
                    "Content-Type": "application/json",
                    REPLAY_HEADER: RUN_ID,
                },
            )

    assert response.status_code == RESPONSE_STATUSES[1]
    assert response.content == RESPONSE_BODIES[1]
    await upstream_client.aclose()
