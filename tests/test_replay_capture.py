"""Replay-with-capture: forensic replay plus optional candidate run recording."""

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
from replayd.testing import compare_runs
from db_backends import close_test_storage, dual_params, open_test_storage

BASELINE_RUN_ID = "baseline-replay-capture"
CANDIDATE_RUN_ID = "candidate-replay-capture"
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
RUN_ID_HEADER = "x-replayd-run-id"


@pytest.fixture
def settings() -> Settings:
    return Settings(REPLAY_HEADER=REPLAY_HEADER, RUN_ID_HEADER=RUN_ID_HEADER)


@pytest.fixture(params=dual_params())
async def populated_baseline(
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
                run_id=BASELINE_RUN_ID,
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


def _request_scope(
    body: bytes,
    *,
    baseline_run_id: str,
    candidate_run_id: str | None = None,
) -> dict[str, object]:
    headers: list[tuple[bytes, bytes]] = [
        (REPLAY_HEADER.encode(), baseline_run_id.encode()),
        (b"content-type", b"application/json"),
    ]
    if candidate_run_id is not None:
        headers.append((RUN_ID_HEADER.encode(), candidate_run_id.encode()))
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
        "headers": headers,
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


async def _replay_all_steps(
    storage: Storage,
    settings: Settings,
    *,
    candidate_run_id: str | None,
) -> list[Response]:
    responses: list[Response] = []
    for body in REQUEST_BODIES:
        scope = _request_scope(
            body,
            baseline_run_id=BASELINE_RUN_ID,
            candidate_run_id=candidate_run_id,
        )
        request = Request(scope, lambda b=body: _receive(b))
        responses.append(await replay_request(request, storage, settings))
    return responses


@pytest.mark.asyncio
async def test_replay_capture_records_candidate_matching_baseline(
    populated_baseline: Storage,
    settings: Settings,
) -> None:
    baseline_count = await populated_baseline.count_exchanges()

    responses = await _replay_all_steps(
        populated_baseline,
        settings,
        candidate_run_id=CANDIDATE_RUN_ID,
    )

    assert all(response.status_code in RESPONSE_STATUSES for response in responses)
    assert await populated_baseline.count_exchanges() == baseline_count + len(REQUEST_BODIES)

    candidate_steps = await populated_baseline.get_run(CANDIDATE_RUN_ID)
    baseline_steps = await populated_baseline.get_run(BASELINE_RUN_ID)
    assert len(candidate_steps) == len(baseline_steps)

    for candidate_step, baseline_step in zip(
        candidate_steps,
        baseline_steps,
        strict=True,
    ):
        assert candidate_step.origin == "replayed"
        assert candidate_step.parent_run_id == BASELINE_RUN_ID
        assert candidate_step.request_body_hash == baseline_step.request_body_hash
        assert candidate_step.response_body_hash == baseline_step.response_body_hash
        assert candidate_step.response_status == baseline_step.response_status

    exact_result = await compare_runs(
        populated_baseline,
        BASELINE_RUN_ID,
        CANDIDATE_RUN_ID,
        mode="exact",
    )
    semantic_result = await compare_runs(
        populated_baseline,
        BASELINE_RUN_ID,
        CANDIDATE_RUN_ID,
        mode="semantic",
    )
    assert exact_result.status == "pass"
    assert semantic_result.status == "pass"


@pytest.mark.asyncio
async def test_replay_capture_divergence_leaves_partial_candidate(
    populated_baseline: Storage,
    settings: Settings,
) -> None:
    baseline_count = await populated_baseline.count_exchanges()

    for body in REQUEST_BODIES[:2]:
        scope = _request_scope(
            body,
            baseline_run_id=BASELINE_RUN_ID,
            candidate_run_id=CANDIDATE_RUN_ID,
        )
        request = Request(scope, lambda b=body: _receive(b))
        response = await replay_request(request, populated_baseline, settings)
        assert response.status_code in RESPONSE_STATUSES[:2]

    unknown_body = b'{"model":"gpt-4o-mini","messages":[{"role":"user","content":"unknown"}]}'
    scope = _request_scope(
        unknown_body,
        baseline_run_id=BASELINE_RUN_ID,
        candidate_run_id=CANDIDATE_RUN_ID,
    )
    request = Request(scope, lambda: _receive(unknown_body))
    divergent = await replay_request(request, populated_baseline, settings)
    payload = json.loads(await _response_body(divergent))

    assert divergent.status_code == 422
    assert payload["error"] == "replay_divergence"
    assert await populated_baseline.count_exchanges() == baseline_count + 2

    candidate_steps = await populated_baseline.get_run(CANDIDATE_RUN_ID)
    assert len(candidate_steps) == 2

    result = await compare_runs(
        populated_baseline,
        BASELINE_RUN_ID,
        CANDIDATE_RUN_ID,
        mode="exact",
    )
    assert result.status == "fail"
    assert "step count mismatch" in result.detail


@pytest.mark.asyncio
async def test_replay_without_candidate_run_id_writes_nothing(
    populated_baseline: Storage,
    settings: Settings,
) -> None:
    before = await populated_baseline.count_exchanges()

    responses = await _replay_all_steps(
        populated_baseline,
        settings,
        candidate_run_id=None,
    )

    assert all(
        response.status_code == status
        for response, status in zip(responses, RESPONSE_STATUSES, strict=True)
    )
    assert await populated_baseline.count_exchanges() == before
    assert await populated_baseline.get_run(CANDIDATE_RUN_ID) == []


@pytest.mark.asyncio
async def test_replay_capture_routing_skips_upstream(
    populated_baseline: Storage,
) -> None:
    async def _forbidden_upstream_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("upstream must not be called during replay capture")

    upstream_client = httpx.AsyncClient(
        transport=httpx.MockTransport(_forbidden_upstream_handler),
        base_url="http://upstream",
    )
    proxy_app = create_app(
        settings=Settings(
            UPSTREAM_BASE_URL="http://upstream",
            REPLAY_HEADER=REPLAY_HEADER,
            RUN_ID_HEADER=RUN_ID_HEADER,
        ),
        http_client=upstream_client,
        storage=populated_baseline,
    )
    transport = httpx.ASGITransport(app=proxy_app)

    async with proxy_app.router.lifespan_context(proxy_app):
        async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
            for body, status in zip(REQUEST_BODIES, RESPONSE_STATUSES, strict=True):
                response = await client.post(
                    "/v1/chat/completions",
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        REPLAY_HEADER: BASELINE_RUN_ID,
                        RUN_ID_HEADER: CANDIDATE_RUN_ID,
                    },
                )
                assert response.status_code == status

    candidate_steps = await populated_baseline.get_run(CANDIDATE_RUN_ID)
    assert len(candidate_steps) == len(REQUEST_BODIES)
    assert all(step.origin == "replayed" for step in candidate_steps)
    await upstream_client.aclose()
