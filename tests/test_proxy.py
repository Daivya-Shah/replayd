import asyncio
import time
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI, Request
from starlette.responses import Response

from replayd.config import Settings
from replayd.main import create_app
from replayd.proxy import filter_request_headers, forward_request

MOCK_BODY = b'{"id":"mock-123","object":"response"}'
MOCK_STATUS = 201
MOCK_AUTH = "Bearer test-secret-key"


@pytest.fixture
def mock_upstream() -> tuple[FastAPI, dict[str, str | None]]:
    captured: dict[str, str | None] = {"authorization": None, "content_length": None}
    upstream = FastAPI()

    @upstream.api_route("/v1/chat/completions", methods=["POST"])
    async def chat_completions(request: Request) -> Response:
        captured["authorization"] = request.headers.get("authorization")
        captured["content_length"] = request.headers.get("content-length")
        captured["content_type"] = request.headers.get("content-type")
        captured["body"] = (await request.body()).decode("utf-8")
        return Response(
            content=MOCK_BODY,
            status_code=MOCK_STATUS,
            media_type="application/json",
        )

    return upstream, captured


@pytest.mark.asyncio
async def test_proxy_forwards_request_transparently(
    mock_upstream: tuple[FastAPI, dict[str, str | None]],
) -> None:
    upstream_app, captured = mock_upstream
    upstream_transport = httpx.ASGITransport(app=upstream_app)
    upstream_client = httpx.AsyncClient(
        transport=upstream_transport,
        base_url="http://upstream",
    )

    settings = Settings(UPSTREAM_BASE_URL="http://upstream", CAPTURE_ENABLED=False)
    proxy_app = create_app(settings=settings, http_client=upstream_client)

    request_body = b'{"model":"gpt-4o","messages":[{"role":"user","content":"hi"}]}'
    proxy_transport = httpx.ASGITransport(app=proxy_app)

    async with proxy_app.router.lifespan_context(proxy_app):
        async with httpx.AsyncClient(
            transport=proxy_transport,
            base_url="http://proxy",
        ) as client:
            response = await client.post(
                "/v1/chat/completions",
                content=request_body,
                headers={
                    "Authorization": MOCK_AUTH,
                    "Content-Type": "application/json",
                    "Host": "proxy.local",
                },
            )

    assert response.status_code == MOCK_STATUS
    assert response.content == MOCK_BODY
    assert captured["authorization"] == MOCK_AUTH
    assert captured["body"] == request_body.decode("utf-8")

    await upstream_client.aclose()


def test_filter_request_headers_strips_content_length() -> None:
    filtered = filter_request_headers(
        {
            "Host": "proxy.local",
            "Content-Length": "999",
            "Authorization": MOCK_AUTH,
            "x-replayd-key": "rpd_secret",
            "X-Replayd-Run-Id": "run-abc",
            "x-replayd-replay": "run-abc",
            "x-replayd-branch": "parent-run",
        }
    )

    lowered = {key.lower() for key in filtered}
    assert "content-length" not in lowered
    assert "host" not in lowered
    assert "x-replayd-key" not in lowered
    assert "x-replayd-run-id" not in lowered
    assert "x-replayd-replay" not in lowered
    assert "x-replayd-branch" not in lowered
    assert filtered["Authorization"] == MOCK_AUTH


@pytest.mark.asyncio
async def test_proxy_does_not_forward_client_content_length(
    mock_upstream: tuple[FastAPI, dict[str, str | None]],
) -> None:
    upstream_app, captured = mock_upstream
    upstream_transport = httpx.ASGITransport(app=upstream_app)
    upstream_client = httpx.AsyncClient(
        transport=upstream_transport,
        base_url="http://upstream",
    )

    settings = Settings(UPSTREAM_BASE_URL="http://upstream", CAPTURE_ENABLED=False)
    proxy_app = create_app(settings=settings, http_client=upstream_client)

    request_body = b'{"model":"gpt-4o","messages":[{"role":"user","content":"hi"}]}'
    proxy_transport = httpx.ASGITransport(app=proxy_app)

    async with proxy_app.router.lifespan_context(proxy_app):
        async with httpx.AsyncClient(
            transport=proxy_transport,
            base_url="http://proxy",
        ) as client:
            response = await client.post(
                "/v1/chat/completions",
                content=request_body,
                headers={
                    "Authorization": MOCK_AUTH,
                    "Content-Type": "application/json",
                    "Content-Length": "1",
                },
            )

    assert response.status_code == MOCK_STATUS
    assert captured["content_length"] != "1"

    await upstream_client.aclose()


SSE_CHUNKS = [
    b'data: {"delta":1}\n\n',
    b'data: {"delta":2}\n\n',
    b"data: [DONE]\n\n",
]
SSE_BODY = b"".join(SSE_CHUNKS)
SSE_CHUNK_DELAY_SECONDS = 0.1


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


@pytest.mark.asyncio
async def test_proxy_streams_sse_incrementally() -> None:
    upstream_client = httpx.AsyncClient(
        transport=httpx.MockTransport(_sse_upstream_handler),
        base_url="http://upstream",
    )

    settings = Settings(UPSTREAM_BASE_URL="http://upstream", CAPTURE_ENABLED=False)
    proxy_app = create_app(settings=settings, http_client=upstream_client)

    async def receive() -> dict[str, object]:
        return {
            "type": "http.request",
            "body": b'{"model":"gpt-4o","stream":true}',
            "more_body": False,
        }

    scope = {
        "type": "http",
        "asgi": {"spec_version": "2.3", "version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/chat/completions",
        "raw_path": b"/v1/chat/completions",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 12345),
        "server": ("proxy", 80),
        "state": {},
    }
    request = Request(scope, receive)

    received_chunks: list[bytes] = []
    first_chunk_elapsed: float | None = None

    async with proxy_app.router.lifespan_context(proxy_app):
        response = await forward_request(request, upstream_client)
        assert response.status_code == 200

        start = time.monotonic()
        async for chunk in response.body_iterator:
            if first_chunk_elapsed is None:
                first_chunk_elapsed = time.monotonic() - start
            received_chunks.append(chunk)

    assert b"".join(received_chunks) == SSE_BODY
    assert len(received_chunks) >= 2
    assert first_chunk_elapsed is not None
    total_upstream_delay = SSE_CHUNK_DELAY_SECONDS * len(SSE_CHUNKS)
    assert first_chunk_elapsed < total_upstream_delay

    await upstream_client.aclose()
