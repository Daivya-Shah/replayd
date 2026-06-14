import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import Request
from starlette.responses import Response, StreamingResponse

from replayd.config import Settings
from replayd.main import create_app
from replayd.management import create_management_app
from replayd.models import Exchange
from replayd.proxy import branch_request
from replayd.storage.base import Storage
from db_backends import close_test_storage, dual_params, open_test_storage

PARENT_RUN_ID = "parent-run-id"
BRANCH_RUN_ID = "branch-run-id"
RUN_ID_HEADER = "x-replayd-run-id"
BRANCH_HEADER = "x-replayd-branch"

PARENT_BODIES = [
    b'{"model":"gpt-4o-mini","messages":[{"role":"user","content":"parent step 1"}]}',
    b'{"model":"gpt-4o-mini","messages":[{"role":"user","content":"parent step 2"}]}',
    b'{"model":"gpt-4o-mini","messages":[{"role":"user","content":"parent step 3"}]}',
]
PARENT_RESPONSES = [
    b'{"id":"p1","choices":[{"message":{"content":"parent reply 1"}}]}',
    b'{"id":"p2","choices":[{"message":{"content":"parent reply 2"}}]}',
    b'{"id":"p3","choices":[{"message":{"content":"parent reply 3"}}]}',
]
DIVERGENT_BODY = b'{"model":"gpt-4o-mini","messages":[{"role":"user","content":"branch diverged"}]}'
LIVE_RESPONSE = b'{"id":"live-1","choices":[{"message":{"content":"live branch reply"}}]}'


@pytest.fixture
def settings() -> Settings:
    return Settings(
        RUN_ID_HEADER=RUN_ID_HEADER,
        BRANCH_HEADER=BRANCH_HEADER,
        REPLAY_HEADER="x-replayd-replay",
    )


@pytest.fixture(params=dual_params())
async def parent_run_storage(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> AsyncIterator[Storage]:
    backend: str = request.param
    storage, schema = await open_test_storage(backend, tmp_path)

    started_at = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)
    for index, (request_body, response_body) in enumerate(
        zip(PARENT_BODIES, PARENT_RESPONSES, strict=True),
    ):
        step_started = started_at + timedelta(seconds=index)
        request_hash = await storage.put_blob(request_body)
        response_hash = await storage.put_blob(response_body)
        await storage.save_exchange(
            Exchange(
                id=uuid.uuid4().hex,
                run_id=PARENT_RUN_ID,
                parent_run_id=None,
                origin="live",
                created_at=step_started,
                started_at=step_started,
                ended_at=step_started + timedelta(milliseconds=10),
                latency_ms=10,
                method="POST",
                path="/v1/chat/completions",
                query=None,
                request_headers={"content-type": "application/json"},
                request_body_hash=request_hash,
                response_status=200 + index,
                response_headers={"content-type": "application/json"},
                model="gpt-4o-mini",
                usage=None,
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


def _branch_scope(
    body: bytes,
    *,
    parent_run_id: str = PARENT_RUN_ID,
    branch_run_id: str = BRANCH_RUN_ID,
) -> dict[str, object]:
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
            (BRANCH_HEADER.encode(), parent_run_id.encode()),
            (RUN_ID_HEADER.encode(), branch_run_id.encode()),
            (b"content-type", b"application/json"),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("proxy", 80),
        "state": {},
    }


async def _response_body(response: Response) -> bytes:
    if isinstance(response, StreamingResponse):
        chunks: list[bytes] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        return b"".join(chunks)
    return response.body


@pytest.mark.asyncio
async def test_branch_match_returns_recorded_response_and_captures_replayed_step(
    parent_run_storage: Storage,
    settings: Settings,
) -> None:
    async def _forbidden_upstream(request: httpx.Request) -> httpx.Response:
        raise AssertionError("upstream must not be called for a branch match")

    upstream_client = httpx.AsyncClient(
        transport=httpx.MockTransport(_forbidden_upstream),
        base_url="http://upstream",
    )
    scope = _branch_scope(PARENT_BODIES[1])
    request = Request(scope, lambda: _receive(PARENT_BODIES[1]))

    response = await branch_request(
        request,
        upstream_client,
        parent_run_storage,
        settings,
    )

    assert response.status_code == 201
    assert await _response_body(response) == PARENT_RESPONSES[1]

    branch_steps = await parent_run_storage.get_run(BRANCH_RUN_ID)
    assert len(branch_steps) == 1
    assert branch_steps[0].parent_run_id == PARENT_RUN_ID
    assert branch_steps[0].origin == "replayed"

    await upstream_client.aclose()


@pytest.mark.asyncio
async def test_branch_miss_forwards_live_and_captures_live_step(
    parent_run_storage: Storage,
    settings: Settings,
) -> None:
    async def _live_upstream(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=httpx.ByteStream(LIVE_RESPONSE),
        )

    upstream_client = httpx.AsyncClient(
        transport=httpx.MockTransport(_live_upstream),
        base_url="http://upstream",
    )
    scope = _branch_scope(DIVERGENT_BODY)
    request = Request(scope, lambda: _receive(DIVERGENT_BODY))

    response = await branch_request(
        request,
        upstream_client,
        parent_run_storage,
        settings,
    )
    assert response.status_code == 200
    assert await _response_body(response) == LIVE_RESPONSE

    branch_steps = await parent_run_storage.get_run(BRANCH_RUN_ID)
    assert len(branch_steps) == 1
    assert branch_steps[0].parent_run_id == PARENT_RUN_ID
    assert branch_steps[0].origin == "live"

    await upstream_client.aclose()


@pytest.mark.asyncio
async def test_branch_run_groups_exchanges_under_branch_and_parent_ids(
    parent_run_storage: Storage,
    settings: Settings,
) -> None:
    async def _live_upstream(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=httpx.ByteStream(LIVE_RESPONSE),
        )

    upstream_client = httpx.AsyncClient(
        transport=httpx.MockTransport(_live_upstream),
        base_url="http://upstream",
    )

    for body in (DIVERGENT_BODY, PARENT_BODIES[1], PARENT_BODIES[2]):
        scope = _branch_scope(body)
        request = Request(scope, lambda b=body: _receive(b))
        response = await branch_request(
            request,
            upstream_client,
            parent_run_storage,
            settings,
        )
        await _response_body(response)

    branch_steps = await parent_run_storage.get_run(BRANCH_RUN_ID)
    assert len(branch_steps) == 3
    assert {step.run_id for step in branch_steps} == {BRANCH_RUN_ID}
    assert {step.parent_run_id for step in branch_steps} == {PARENT_RUN_ID}
    assert branch_steps[0].origin == "live"
    assert branch_steps[1].origin == "replayed"
    assert branch_steps[2].origin == "replayed"

    await upstream_client.aclose()


@pytest.mark.asyncio
async def test_control_api_exposes_parent_run_id_and_step_origin(
    parent_run_storage: Storage,
    settings: Settings,
) -> None:
    started_at = datetime(2026, 6, 12, 13, 0, 0, tzinfo=UTC)
    request_hash = await parent_run_storage.put_blob(PARENT_BODIES[1])
    response_hash = await parent_run_storage.put_blob(PARENT_RESPONSES[1])
    await parent_run_storage.save_exchange(
        Exchange(
            id=uuid.uuid4().hex,
            run_id=BRANCH_RUN_ID,
            parent_run_id=PARENT_RUN_ID,
            origin="replayed",
            created_at=started_at,
            started_at=started_at,
            ended_at=started_at,
            latency_ms=8,
            method="POST",
            path="/v1/chat/completions",
            query=None,
            request_headers={"content-type": "application/json"},
            request_body_hash=request_hash,
            response_status=201,
            response_headers={"content-type": "application/json"},
            model="gpt-4o-mini",
            usage=None,
            provider=None,
            response_body_hash=response_hash,
        )
    )

    app = create_management_app(settings=settings, storage=parent_run_storage)
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://mgmt") as client:
            list_response = await client.get("/api/runs")
            detail_response = await client.get(f"/api/runs/{BRANCH_RUN_ID}")

    list_payload = list_response.json()
    branch_summary = next(item for item in list_payload["items"] if item["run_id"] == BRANCH_RUN_ID)
    assert branch_summary["parent_run_id"] == PARENT_RUN_ID

    detail_payload = detail_response.json()
    assert detail_payload["parent_run_id"] == PARENT_RUN_ID
    assert detail_payload["steps"][0]["origin"] == "replayed"
    assert detail_payload["steps"][0]["parent_run_id"] == PARENT_RUN_ID
