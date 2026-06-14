"""Proxy ingest-key resolution and multi-tenant attribution tests."""

from __future__ import annotations

import types
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI, Request
from starlette.responses import Response

from replayd.config import Settings
from replayd.main import create_app
from replayd.models import Organization, Project, ProjectIngestKey
from replayd.proxy import forward_request
from replayd.storage.base import Storage
from replayd.tenancy import DEFAULT_PROJECT_ID

REQUEST_BODY = b'{"model":"gpt-4o","messages":[{"role":"user","content":"hi"}]}'
MOCK_BODY = b'{"id":"mock-123","object":"response"}'
MOCK_STATUS = 201

OTHER_ORG_ID = "00000000-0000-4000-8000-000000000098"
OTHER_PROJECT_ID = "00000000-0000-4000-8000-000000000099"


def _now() -> datetime:
    return datetime(2026, 6, 13, 12, 0, 0, tzinfo=UTC)


async def _seed_project(storage: Storage, org_id: str, project_id: str) -> None:
    await storage.create_organization(
        Organization(
            id=org_id,
            name="Test Org",
            slug=f"org-{org_id[:8]}",
            created_at=_now(),
        )
    )
    await storage.create_project(
        Project(
            id=project_id,
            org_id=org_id,
            name="Test Project",
            slug=f"proj-{project_id[:8]}",
            created_at=_now(),
        )
    )


@pytest.fixture
def capturing_upstream() -> tuple[FastAPI, dict[str, object]]:
    captured: dict[str, object] = {"called": False, "headers": {}}
    upstream = FastAPI()

    @upstream.api_route("/v1/chat/completions", methods=["POST"])
    async def chat_completions(request: Request) -> Response:
        captured["called"] = True
        captured["headers"] = {key.lower(): value for key, value in request.headers.items()}
        await request.body()
        return Response(
            content=MOCK_BODY,
            status_code=MOCK_STATUS,
            media_type="application/json",
        )

    return upstream, captured


async def _receive(body: bytes) -> dict[str, object]:
    return {"type": "http.request", "body": body, "more_body": False}


def _request_scope(headers: list[tuple[bytes, bytes]]) -> dict[str, object]:
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


async def _forward_and_drain(
    storage: Storage,
    upstream: FastAPI,
    headers: list[tuple[bytes, bytes]],
    *,
    settings: Settings | None = None,
) -> httpx.Response:
    upstream_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=upstream),
        base_url="http://upstream",
    )
    scope = _request_scope(headers)
    request = Request(scope, lambda: _receive(REQUEST_BODY))
    response = await forward_request(
        request,
        upstream_client,
        storage=storage,
        settings=settings or Settings(),
    )
    async for _chunk in response.body_iterator:
        pass
    await upstream_client.aclose()
    return response


@pytest.mark.asyncio
async def test_valid_ingest_key_attributes_exchange_and_updates_last_used(
    core_storage: Storage,
    capturing_upstream: tuple[FastAPI, dict[str, object]],
) -> None:
    upstream, _captured = capturing_upstream
    await _seed_project(core_storage, OTHER_ORG_ID, OTHER_PROJECT_ID)
    _key_model, plaintext = await core_storage.create_ingest_key(
        OTHER_PROJECT_ID,
        "agent-key",
    )

    headers = [
        (b"x-replayd-key", plaintext.encode()),
        (b"content-type", b"application/json"),
    ]
    response = await _forward_and_drain(core_storage, upstream, headers)
    assert response.status_code == MOCK_STATUS

    exchanges = await core_storage.list_exchanges()
    assert len(exchanges) == 1
    assert exchanges[0].project_id == OTHER_PROJECT_ID

    keys = await core_storage.list_ingest_keys(OTHER_PROJECT_ID)
    assert len(keys) == 1
    assert keys[0].last_used_at is not None


@pytest.mark.asyncio
async def test_no_key_lenient_attributes_default_project(
    core_storage: Storage,
    capturing_upstream: tuple[FastAPI, dict[str, object]],
) -> None:
    upstream, captured = capturing_upstream
    headers = [(b"content-type", b"application/json")]
    response = await _forward_and_drain(core_storage, upstream, headers)
    assert response.status_code == MOCK_STATUS
    assert captured["called"] is True

    exchanges = await core_storage.list_exchanges()
    assert len(exchanges) == 1
    assert exchanges[0].project_id == DEFAULT_PROJECT_ID


@pytest.mark.asyncio
async def test_invalid_key_lenient_still_forwards_with_default_project(
    core_storage: Storage,
    capturing_upstream: tuple[FastAPI, dict[str, object]],
) -> None:
    upstream, captured = capturing_upstream
    await _seed_project(core_storage, OTHER_ORG_ID, OTHER_PROJECT_ID)
    _key_model, _plaintext = await core_storage.create_ingest_key(
        OTHER_PROJECT_ID,
        "agent-key",
    )

    headers = [
        (b"x-replayd-key", b"rpd_totally_wrong_token"),
        (b"content-type", b"application/json"),
    ]
    response = await _forward_and_drain(core_storage, upstream, headers)
    assert response.status_code == MOCK_STATUS
    assert captured["called"] is True

    exchanges = await core_storage.list_exchanges()
    assert len(exchanges) == 1
    assert exchanges[0].project_id == DEFAULT_PROJECT_ID
    assert exchanges[0].project_id != OTHER_PROJECT_ID


@pytest.mark.asyncio
async def test_replayd_control_headers_not_forwarded_upstream(
    core_storage: Storage,
    capturing_upstream: tuple[FastAPI, dict[str, object]],
) -> None:
    upstream, captured = capturing_upstream
    headers = [
        (b"x-replayd-key", b"rpd_ignored"),
        (b"x-replayd-run-id", b"run-abc"),
        (b"x-replayd-replay", b"run-abc"),
        (b"x-replayd-branch", b"parent-run"),
        (b"authorization", b"Bearer provider-key"),
        (b"content-type", b"application/json"),
    ]
    await _forward_and_drain(core_storage, upstream, headers)

    upstream_headers = captured["headers"]
    assert isinstance(upstream_headers, dict)
    assert "x-replayd-key" not in upstream_headers
    assert "x-replayd-run-id" not in upstream_headers
    assert "x-replayd-replay" not in upstream_headers
    assert "x-replayd-branch" not in upstream_headers
    assert upstream_headers.get("authorization") == "Bearer provider-key"


@pytest.mark.asyncio
async def test_resolve_ingest_key_failure_does_not_break_forwarded_request(
    core_storage: Storage,
    capturing_upstream: tuple[FastAPI, dict[str, object]],
) -> None:
    upstream, captured = capturing_upstream

    async def failing_resolve(_plaintext: str) -> ProjectIngestKey | None:
        raise RuntimeError("simulated resolve failure")

    core_storage.resolve_ingest_key = types.MethodType(failing_resolve, core_storage)

    headers = [
        (b"x-replayd-key", b"rpd_anything"),
        (b"content-type", b"application/json"),
    ]
    response = await _forward_and_drain(core_storage, upstream, headers)
    assert response.status_code == MOCK_STATUS
    assert captured["called"] is True

    exchanges = await core_storage.list_exchanges()
    assert len(exchanges) == 1
    assert exchanges[0].project_id == DEFAULT_PROJECT_ID


@pytest.mark.asyncio
async def test_strict_mode_rejects_missing_key_before_upstream(
    core_storage: Storage,
    capturing_upstream: tuple[FastAPI, dict[str, object]],
) -> None:
    upstream, captured = capturing_upstream
    upstream_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=upstream),
        base_url="http://upstream",
    )
    settings = Settings(REQUIRE_INGEST_KEY=True)
    proxy_app = create_app(
        settings=settings,
        http_client=upstream_client,
        storage=core_storage,
    )

    async with proxy_app.router.lifespan_context(proxy_app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=proxy_app),
            base_url="http://proxy",
        ) as client:
            response = await client.post(
                "/v1/chat/completions",
                content=REQUEST_BODY,
                headers={"Content-Type": "application/json"},
            )

    assert response.status_code == 401
    assert captured["called"] is False
    assert await core_storage.list_exchanges() == []
    await upstream_client.aclose()


@pytest.mark.asyncio
async def test_strict_mode_rejects_invalid_key_before_upstream(
    core_storage: Storage,
    capturing_upstream: tuple[FastAPI, dict[str, object]],
) -> None:
    upstream, captured = capturing_upstream
    await _seed_project(core_storage, OTHER_ORG_ID, OTHER_PROJECT_ID)
    await core_storage.create_ingest_key(OTHER_PROJECT_ID, "agent-key")

    upstream_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=upstream),
        base_url="http://upstream",
    )
    settings = Settings(REQUIRE_INGEST_KEY=True)
    proxy_app = create_app(
        settings=settings,
        http_client=upstream_client,
        storage=core_storage,
    )

    async with proxy_app.router.lifespan_context(proxy_app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=proxy_app),
            base_url="http://proxy",
        ) as client:
            response = await client.post(
                "/v1/chat/completions",
                content=REQUEST_BODY,
                headers={
                    "Content-Type": "application/json",
                    "x-replayd-key": "rpd_wrong_token",
                },
            )

    assert response.status_code == 401
    assert captured["called"] is False
    assert await core_storage.list_exchanges() == []
    await upstream_client.aclose()


@pytest.mark.asyncio
async def test_strict_mode_forwards_and_attributes_with_valid_key(
    core_storage: Storage,
    capturing_upstream: tuple[FastAPI, dict[str, object]],
) -> None:
    upstream, captured = capturing_upstream
    await _seed_project(core_storage, OTHER_ORG_ID, OTHER_PROJECT_ID)
    _key_model, plaintext = await core_storage.create_ingest_key(
        OTHER_PROJECT_ID,
        "agent-key",
    )

    upstream_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=upstream),
        base_url="http://upstream",
    )
    settings = Settings(REQUIRE_INGEST_KEY=True, CAPTURE_ENABLED=True)
    proxy_app = create_app(
        settings=settings,
        http_client=upstream_client,
        storage=core_storage,
    )

    async with proxy_app.router.lifespan_context(proxy_app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=proxy_app),
            base_url="http://proxy",
        ) as client:
            response = await client.post(
                "/v1/chat/completions",
                content=REQUEST_BODY,
                headers={
                    "Content-Type": "application/json",
                    "x-replayd-key": plaintext,
                },
            )

    assert response.status_code == MOCK_STATUS
    assert captured["called"] is True
    exchanges = await core_storage.list_exchanges()
    assert len(exchanges) == 1
    assert exchanges[0].project_id == OTHER_PROJECT_ID
    await upstream_client.aclose()
