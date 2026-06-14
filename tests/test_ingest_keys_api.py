"""Control-plane ingest-key management API tests."""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, Request
from starlette.responses import Response

from replayd.auth.principal import provision_user_principal
from replayd.auth.tenancy import resolve_accessible_project_ids
from replayd.config import Settings
from replayd.management import create_management_app
from replayd.proxy import forward_request
from replayd.storage.base import Storage
from replayd.tenancy import DEFAULT_PROJECT_ID
from test_oidc import (
    _generate_rsa_keypair,
    _management_client,
    _mint_jwt,
    _oidc_settings,
    _verifier_for_public_key,
)

REQUEST_BODY = b'{"model":"gpt-4o","messages":[{"role":"user","content":"hi"}]}'
MOCK_BODY = b'{"id":"mock-123","object":"response"}'
MOCK_STATUS = 201


@pytest.fixture
def rsa_keypair() -> tuple[object, object]:
    return _generate_rsa_keypair()


def _unscoped_client(
    storage: Storage,
    tmp_path: Path,
) -> tuple[httpx.AsyncClient, object]:
    settings = Settings(STORAGE_DIR=str(tmp_path))
    app = create_management_app(settings=settings, storage=storage)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://mgmt"), app


async def _provision_user(
    storage: Storage,
    *,
    subject: str,
    email: str,
) -> str:
    principal = await provision_user_principal(
        storage,
        subject=subject,
        email=email,
        name=email.split("@")[0].title(),
    )
    project_ids = await resolve_accessible_project_ids(storage, principal)
    assert len(project_ids) == 1
    return project_ids[0]


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


@pytest.fixture
def capturing_upstream() -> FastAPI:
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


async def _forward_with_key(
    storage: Storage,
    upstream: FastAPI,
    plaintext: str,
) -> httpx.Response:
    upstream_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=upstream),
        base_url="http://upstream",
    )
    headers = [
        (b"x-replayd-key", plaintext.encode()),
        (b"content-type", b"application/json"),
    ]
    scope = _request_scope(headers)
    request = Request(scope, lambda: _receive(REQUEST_BODY))
    response = await forward_request(
        request,
        upstream_client,
        storage=storage,
        settings=Settings(),
    )
    async for _chunk in response.body_iterator:
        pass
    await upstream_client.aclose()
    return response


@pytest.mark.asyncio
async def test_create_returns_plaintext_token_once(
    core_storage: Storage,
    tmp_path: Path,
) -> None:
    client, app = _unscoped_client(core_storage, tmp_path)

    async with app.router.lifespan_context(app):
        async with client:
            create_resp = await client.post(
                "/api/ingest-keys",
                json={"name": "ci-agent"},
            )
            list_resp = await client.get("/api/ingest-keys")

    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["token"].startswith("rpd_")
    assert created["prefix"] == created["token"][:12]
    assert created["name"] == "ci-agent"
    assert "key_hash" not in created

    assert list_resp.status_code == 200
    listed = list_resp.json()
    assert listed["total"] == 1
    item = listed["items"][0]
    assert item["id"] == created["id"]
    assert item["prefix"] == created["prefix"]
    assert "token" not in item
    assert "key_hash" not in item


@pytest.mark.asyncio
async def test_created_key_resolves_on_proxy_capture_path(
    core_storage: Storage,
    tmp_path: Path,
    capturing_upstream: FastAPI,
) -> None:
    client, app = _unscoped_client(core_storage, tmp_path)

    async with app.router.lifespan_context(app):
        async with client:
            create_resp = await client.post("/api/ingest-keys", json={"name": "proxy-key"})

    plaintext = create_resp.json()["token"]
    response = await _forward_with_key(core_storage, capturing_upstream, plaintext)
    assert response.status_code == MOCK_STATUS

    resolved = await core_storage.resolve_ingest_key(plaintext)
    assert resolved is not None

    exchanges = await core_storage.list_exchanges()
    assert len(exchanges) == 1
    assert exchanges[0].project_id == DEFAULT_PROJECT_ID


@pytest.mark.asyncio
async def test_users_cannot_list_or_revoke_other_project_keys(
    core_storage: Storage,
    rsa_keypair: tuple[object, object],
    tmp_path: Path,
) -> None:
    private_key, public_key = rsa_keypair
    settings = _oidc_settings(tmp_path)
    client, app = _management_client(
        core_storage,
        settings,
        _verifier_for_public_key(settings, public_key),
    )

    subject_a = f"ingest-user-a-{uuid.uuid4().hex[:8]}"
    subject_b = f"ingest-user-b-{uuid.uuid4().hex[:8]}"
    project_a = await _provision_user(core_storage, subject=subject_a, email="a@example.com")
    await _provision_user(core_storage, subject=subject_b, email="b@example.com")

    token_a = _mint_jwt(private_key, sub=subject_a, email="a@example.com")
    token_b = _mint_jwt(private_key, sub=subject_b, email="b@example.com")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    async with app.router.lifespan_context(app):
        async with client:
            create_resp = await client.post(
                "/api/ingest-keys",
                json={"name": "user-a-key"},
                headers=headers_a,
            )
            list_b = await client.get("/api/ingest-keys", headers=headers_b)
            revoke_b = await client.delete(
                f"/api/ingest-keys/{create_resp.json()['id']}",
                headers=headers_b,
            )

    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["project_id"] == project_a
    assert "token" in created

    assert list_b.status_code == 200
    assert list_b.json()["total"] == 0

    assert revoke_b.status_code == 404

    resolved = await core_storage.resolve_ingest_key(created["token"])
    assert resolved is not None


@pytest.mark.asyncio
async def test_revoked_key_no_longer_resolves(
    core_storage: Storage,
    tmp_path: Path,
    capturing_upstream: FastAPI,
) -> None:
    client, app = _unscoped_client(core_storage, tmp_path)

    async with app.router.lifespan_context(app):
        async with client:
            create_resp = await client.post("/api/ingest-keys", json={"name": "revoke-me"})
            key_id = create_resp.json()["id"]
            plaintext = create_resp.json()["token"]
            revoke_resp = await client.delete(f"/api/ingest-keys/{key_id}")

    assert revoke_resp.status_code == 204
    assert await core_storage.resolve_ingest_key(plaintext) is None

    response = await _forward_with_key(core_storage, capturing_upstream, plaintext)
    assert response.status_code == MOCK_STATUS

    exchanges = await core_storage.list_exchanges(project_ids=[DEFAULT_PROJECT_ID])
    assert len(exchanges) == 1
    assert exchanges[0].project_id == DEFAULT_PROJECT_ID
