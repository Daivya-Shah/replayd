import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, Request
from starlette.responses import Response

from replayd.models import Exchange
from replayd.proxy import forward_request
from replayd.redaction import REDACTED_VALUE
from replayd.storage.sqlite import SqliteStorage

MOCK_BODY = b'{"id":"mock-123","object":"response","usage":{"prompt_tokens":1,"completion_tokens":2,"total_tokens":3}}'
MOCK_STATUS = 201
MOCK_AUTH = "Bearer test-secret-key"
REQUEST_BODY = b'{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hi"}]}'

SSE_CHUNKS = [
    b'data: {"delta":1}\n\n',
    b'data: {"delta":2}\n\n',
    b"data: [DONE]\n\n",
]
SSE_BODY = b"".join(SSE_CHUNKS)
SSE_CHUNK_DELAY_SECONDS = 0.1


@pytest.fixture
async def storage(tmp_path: Path) -> AsyncIterator[SqliteStorage]:
    store = SqliteStorage(str(tmp_path))
    await store.init()
    yield store
    await store.aclose()


@pytest.fixture
def mock_upstream() -> FastAPI:
    upstream = FastAPI()

    @upstream.api_route("/v1/chat/completions", methods=["POST"])
    async def chat_completions(request: Request) -> Response:
        await request.body()
        return Response(
            content=MOCK_BODY,
            status_code=MOCK_STATUS,
            media_type="application/json",
        )

    return upstream


class _DelayedChunkStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in SSE_CHUNKS:
            await asyncio.sleep(SSE_CHUNK_DELAY_SECONDS)
            yield chunk


async def _sse_upstream_handler(request: httpx.Request) -> httpx.Response:
    del request
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        stream=_DelayedChunkStream(),
    )


async def _receive(body: bytes) -> dict[str, object]:
    return {"type": "http.request", "body": body, "more_body": False}


def _request_scope(body: bytes, headers: list[tuple[bytes, bytes]]) -> dict[str, object]:
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


@pytest.mark.asyncio
async def test_capture_non_streaming_exchange_and_blobs(
    storage: SqliteStorage,
    mock_upstream: FastAPI,
) -> None:
    upstream_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mock_upstream),
        base_url="http://upstream",
    )
    scope = _request_scope(
        REQUEST_BODY,
        [
            (b"authorization", MOCK_AUTH.encode()),
            (b"content-type", b"application/json"),
        ],
    )
    request = Request(scope, lambda: _receive(REQUEST_BODY))

    response = await forward_request(request, upstream_client, storage=storage)
    assert response.status_code == MOCK_STATUS
    body = b"".join([chunk async for chunk in response.body_iterator])
    assert body == MOCK_BODY

    exchanges = await storage.list_exchanges()
    assert len(exchanges) == 1
    exchange = exchanges[0]
    assert exchange.request_body_hash is not None
    assert exchange.response_body_hash is not None
    assert await storage.get_blob(exchange.request_body_hash) == REQUEST_BODY
    assert await storage.get_blob(exchange.response_body_hash) == MOCK_BODY
    assert exchange.latency_ms >= 0
    auth_header = next(
        value
        for key, value in exchange.request_headers.items()
        if key.lower() == "authorization"
    )
    assert auth_header == REDACTED_VALUE

    await upstream_client.aclose()


@pytest.mark.asyncio
async def test_capture_streaming_exchange_with_incremental_client_delivery(
    storage: SqliteStorage,
) -> None:
    upstream_client = httpx.AsyncClient(
        transport=httpx.MockTransport(_sse_upstream_handler),
        base_url="http://upstream",
    )
    scope = _request_scope(
        b'{"model":"gpt-4o-mini","stream":true}',
        [(b"content-type", b"application/json")],
    )
    request = Request(
        scope,
        lambda: _receive(b'{"model":"gpt-4o-mini","stream":true}'),
    )

    response = await forward_request(request, upstream_client, storage=storage)
    assert response.status_code == 200

    received_chunks: list[bytes] = []
    first_chunk_elapsed: float | None = None
    start = time.monotonic()
    async for chunk in response.body_iterator:
        if first_chunk_elapsed is None:
            first_chunk_elapsed = time.monotonic() - start
        received_chunks.append(chunk)

    assert b"".join(received_chunks) == SSE_BODY
    assert len(received_chunks) >= 2
    assert first_chunk_elapsed is not None
    assert first_chunk_elapsed < SSE_CHUNK_DELAY_SECONDS * len(SSE_CHUNKS)

    exchanges = await storage.list_exchanges()
    assert len(exchanges) == 1
    exchange = exchanges[0]
    assert exchange.response_body_hash is not None
    assert await storage.get_blob(exchange.response_body_hash) == SSE_BODY

    await upstream_client.aclose()


@pytest.mark.asyncio
async def test_capture_isolation_when_save_exchange_fails(
    tmp_path: Path,
    mock_upstream: FastAPI,
) -> None:
    class FailingStorage(SqliteStorage):
        async def save_exchange(self, exchange: Exchange) -> None:
            del exchange
            raise RuntimeError("simulated capture failure")

    failing_storage = FailingStorage(str(tmp_path))
    await failing_storage.init()

    upstream_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mock_upstream),
        base_url="http://upstream",
    )
    scope = _request_scope(REQUEST_BODY, [(b"content-type", b"application/json")])
    request = Request(scope, lambda: _receive(REQUEST_BODY))

    response = await forward_request(request, upstream_client, storage=failing_storage)
    assert response.status_code == MOCK_STATUS
    body = b"".join([chunk async for chunk in response.body_iterator])
    assert body == MOCK_BODY
    assert await failing_storage.list_exchanges() == []

    await upstream_client.aclose()
    await failing_storage.aclose()


@pytest.mark.asyncio
async def test_capture_extracts_model_from_request_body(
    storage: SqliteStorage,
    mock_upstream: FastAPI,
) -> None:
    upstream_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mock_upstream),
        base_url="http://upstream",
    )
    scope = _request_scope(REQUEST_BODY, [(b"content-type", b"application/json")])
    request = Request(scope, lambda: _receive(REQUEST_BODY))

    response = await forward_request(request, upstream_client, storage=storage)
    async for _chunk in response.body_iterator:
        pass

    exchange = (await storage.list_exchanges())[0]
    assert exchange.model == "gpt-4o-mini"

    await upstream_client.aclose()


@pytest.mark.asyncio
async def test_capture_uses_run_id_header_when_present(
    storage: SqliteStorage,
    mock_upstream: FastAPI,
) -> None:
    run_id = "agent-run-abc123"
    upstream_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mock_upstream),
        base_url="http://upstream",
    )
    scope = _request_scope(
        REQUEST_BODY,
        [
            (b"x-replayd-run-id", run_id.encode()),
            (b"content-type", b"application/json"),
        ],
    )
    request = Request(scope, lambda: _receive(REQUEST_BODY))

    response = await forward_request(request, upstream_client, storage=storage)
    async for _chunk in response.body_iterator:
        pass

    exchange = (await storage.list_exchanges())[0]
    assert exchange.run_id == run_id
    header_value = next(
        value
        for key, value in exchange.request_headers.items()
        if key.lower() == "x-replayd-run-id"
    )
    assert header_value == run_id

    await upstream_client.aclose()


@pytest.mark.asyncio
async def test_capture_generates_unique_run_id_without_header(
    storage: SqliteStorage,
    mock_upstream: FastAPI,
) -> None:
    upstream_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mock_upstream),
        base_url="http://upstream",
    )
    scope = _request_scope(REQUEST_BODY, [(b"content-type", b"application/json")])
    run_ids: list[str] = []

    for _ in range(2):
        request = Request(scope, lambda: _receive(REQUEST_BODY))
        response = await forward_request(request, upstream_client, storage=storage)
        async for _chunk in response.body_iterator:
            pass
        run_ids.append((await storage.list_exchanges(limit=1))[0].run_id)

    assert run_ids[0] != run_ids[1]

    await upstream_client.aclose()
