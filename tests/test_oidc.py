"""OIDC JWT authentication and principal resolution tests."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import ECAlgorithm, RSAAlgorithm
from starlette.requests import Request

from replayd.auth.oidc import InjectedJwksClient, OidcAuthError, OidcVerifier, oidc_configured, resolve_jwks_url
from replayd.auth.principal import (
    AuthenticationError,
    Principal,
    auth_configured,
    resolve_principal,
)
from replayd.config import Settings
from replayd.check_oidc import OidcConnectivityError, verify_oidc_connectivity
from replayd.management import create_management_app
from replayd.storage.base import Storage

TEST_ISSUER = "https://test-issuer.example"
TEST_AUDIENCE = "replayd-control-plane"
TEST_KID = "test-signing-key"
API_TOKEN = "test-control-plane-token"


def _generate_rsa_keypair() -> tuple[object, object]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _jwks_from_public_key(public_key: object, *, kid: str = TEST_KID) -> dict[str, object]:
    jwk = json.loads(RSAAlgorithm.to_jwk(public_key))
    jwk["kid"] = kid
    jwk["use"] = "sig"
    jwk["alg"] = "RS256"
    return {"keys": [jwk]}


def _mint_jwt(
    private_key: object,
    *,
    sub: str,
    email: str | None = "user@example.com",
    name: str | None = "Test User",
    issuer: str = TEST_ISSUER,
    audience: str = TEST_AUDIENCE,
    exp_seconds: int = 3600,
    algorithm: str = "RS256",
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "sub": sub,
        "iss": issuer,
        "aud": audience,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()) - 5,
        "exp": int((now + timedelta(seconds=exp_seconds)).timestamp()),
    }
    if email is not None:
        payload["email"] = email
    if name is not None:
        payload["name"] = name
    return jwt.encode(
        payload,
        private_key,
        algorithm=algorithm,
        headers={"kid": TEST_KID},
    )


def _oidc_settings(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(
        STORAGE_DIR=str(tmp_path),
        OIDC_ISSUER=TEST_ISSUER,
        OIDC_AUDIENCE=TEST_AUDIENCE,
        **overrides,
    )


def _verifier_for_public_key(
    settings: Settings,
    public_key: object,
) -> OidcVerifier:
    jwks = _jwks_from_public_key(public_key)
    return OidcVerifier(settings, jwks_client=InjectedJwksClient(jwks))


def _request_with_bearer(token: str) -> Request:
    scope: dict[str, object] = {
        "type": "http",
        "method": "GET",
        "path": "/api/runs",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
    }
    return Request(scope)


def _management_client(
    storage: Storage,
    settings: Settings,
    verifier: OidcVerifier,
) -> tuple[httpx.AsyncClient, object]:
    app = create_management_app(
        settings=settings,
        storage=storage,
        oidc_verifier=verifier,
    )
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://mgmt"), app


@pytest.fixture
def rsa_keypair() -> tuple[object, object]:
    return _generate_rsa_keypair()


def test_verifier_validates_rs256_jwt_with_injected_jwks(
    rsa_keypair: tuple[object, object],
    tmp_path: Path,
) -> None:
    private_key, public_key = rsa_keypair
    settings = _oidc_settings(tmp_path)
    verifier = _verifier_for_public_key(settings, public_key)
    token = _mint_jwt(private_key, sub="user-sub-1")

    claims = verifier.verify(token)

    assert claims.sub == "user-sub-1"
    assert claims.email == "user@example.com"
    assert claims.name == "Test User"


def test_verifier_validates_es384_jwt_with_injected_jwks(tmp_path: Path) -> None:
    private_key = ec.generate_private_key(ec.SECP384R1())
    public_key = private_key.public_key()
    settings = _oidc_settings(tmp_path)
    jwk = json.loads(ECAlgorithm.to_jwk(public_key))
    jwk["kid"] = TEST_KID
    jwk["use"] = "sig"
    jwk["alg"] = "ES384"
    verifier = OidcVerifier(
        settings,
        jwks_client=InjectedJwksClient({"keys": [jwk]}),
    )
    token = _mint_jwt(private_key, sub="es384-user", algorithm="ES384")

    claims = verifier.verify(token)

    assert claims.sub == "es384-user"


@pytest.mark.asyncio
async def test_valid_jwt_yields_user_principal(
    core_storage: Storage,
    rsa_keypair: tuple[object, object],
    tmp_path: Path,
) -> None:
    private_key, public_key = rsa_keypair
    settings = _oidc_settings(tmp_path)
    verifier = _verifier_for_public_key(settings, public_key)
    token = _mint_jwt(private_key, sub="principal-sub-1")
    request = _request_with_bearer(token)

    principal = await resolve_principal(request, core_storage, settings, verifier)

    assert principal == Principal(kind="user", user_id=principal.user_id)
    assert principal.user_id is not None
    user = await core_storage.get_user_by_subject("principal-sub-1")
    assert user is not None
    assert user.id == principal.user_id


@pytest.mark.asyncio
async def test_jit_provisioning_creates_user_on_first_request(
    core_storage: Storage,
    rsa_keypair: tuple[object, object],
    tmp_path: Path,
) -> None:
    private_key, public_key = rsa_keypair
    settings = _oidc_settings(tmp_path)
    verifier = _verifier_for_public_key(settings, public_key)
    client, app = _management_client(core_storage, settings, verifier)
    subject = f"jit-user-{uuid.uuid4().hex[:8]}"
    token = _mint_jwt(
        private_key,
        sub=subject,
        email="jit@example.com",
        name="JIT User",
    )

    async with app.router.lifespan_context(app):
        async with client:
            assert await core_storage.get_user_by_subject(subject) is None
            response = await client.get(
                "/api/runs",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert response.status_code == 200
    user = await core_storage.get_user_by_subject(subject)
    assert user is not None
    assert user.email == "jit@example.com"
    assert user.name == "JIT User"


@pytest.mark.asyncio
async def test_jit_provisioning_reuses_existing_user_on_second_request(
    core_storage: Storage,
    rsa_keypair: tuple[object, object],
    tmp_path: Path,
) -> None:
    private_key, public_key = rsa_keypair
    settings = _oidc_settings(tmp_path)
    verifier = _verifier_for_public_key(settings, public_key)
    client, app = _management_client(core_storage, settings, verifier)
    subject = f"reuse-user-{uuid.uuid4().hex[:8]}"
    token = _mint_jwt(private_key, sub=subject, email="reuse@example.com")

    async with app.router.lifespan_context(app):
        async with client:
            first = await client.get(
                "/api/runs",
                headers={"Authorization": f"Bearer {token}"},
            )
            user_after_first = await core_storage.get_user_by_subject(subject)
            second = await client.get(
                "/api/runs",
                headers={"Authorization": f"Bearer {token}"},
            )
            user_after_second = await core_storage.get_user_by_subject(subject)

    assert first.status_code == 200
    assert second.status_code == 200
    assert user_after_first is not None
    assert user_after_second is not None
    assert user_after_first.id == user_after_second.id


@pytest.mark.parametrize(
    ("mutator", "description"),
    [
        ("bad_signature", "bad signature"),
        ("wrong_aud", "wrong audience"),
        ("wrong_iss", "wrong issuer"),
        ("expired", "expired token"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_jwt_is_rejected(
    core_storage: Storage,
    rsa_keypair: tuple[object, object],
    tmp_path: Path,
    mutator: str,
    description: str,
) -> None:
    del description
    private_key, public_key = rsa_keypair
    other_private, _other_public = _generate_rsa_keypair()
    settings = _oidc_settings(tmp_path)
    verifier = _verifier_for_public_key(settings, public_key)
    client, app = _management_client(core_storage, settings, verifier)

    if mutator == "bad_signature":
        token = _mint_jwt(other_private, sub="bad-sig-user")
    elif mutator == "wrong_aud":
        token = _mint_jwt(private_key, sub="bad-aud-user", audience="wrong-audience")
    elif mutator == "wrong_iss":
        token = _mint_jwt(private_key, sub="bad-iss-user", issuer="https://wrong-issuer")
    elif mutator == "expired":
        token = _mint_jwt(private_key, sub="expired-user", exp_seconds=-60)
    else:
        raise AssertionError(f"unknown mutator {mutator}")

    async with app.router.lifespan_context(app):
        async with client:
            response = await client.get(
                "/api/runs",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


def test_verifier_raises_on_invalid_token(
    rsa_keypair: tuple[object, object],
    tmp_path: Path,
) -> None:
    private_key, public_key = rsa_keypair
    other_private, _ = _generate_rsa_keypair()
    settings = _oidc_settings(tmp_path)
    verifier = _verifier_for_public_key(settings, public_key)
    token = _mint_jwt(other_private, sub="bad-sig")

    with pytest.raises(OidcAuthError):
        verifier.verify(token)


@pytest.mark.asyncio
async def test_shared_token_yields_service_principal_with_oidc_configured(
    core_storage: Storage,
    rsa_keypair: tuple[object, object],
    tmp_path: Path,
) -> None:
    _private_key, public_key = rsa_keypair
    settings = _oidc_settings(tmp_path, REPLAYD_API_TOKEN=API_TOKEN)
    verifier = _verifier_for_public_key(settings, public_key)
    request = _request_with_bearer(API_TOKEN)

    principal = await resolve_principal(request, core_storage, settings, verifier)

    assert principal == Principal(kind="service", user_id=None)


@pytest.mark.asyncio
async def test_shared_token_works_via_http_with_oidc_configured(
    core_storage: Storage,
    rsa_keypair: tuple[object, object],
    tmp_path: Path,
) -> None:
    _private_key, public_key = rsa_keypair
    settings = _oidc_settings(tmp_path, REPLAYD_API_TOKEN=API_TOKEN)
    verifier = _verifier_for_public_key(settings, public_key)
    client, app = _management_client(core_storage, settings, verifier)

    async with app.router.lifespan_context(app):
        async with client:
            response = await client.get(
                "/api/runs",
                headers={"Authorization": f"Bearer {API_TOKEN}"},
            )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_dev_mode_yields_anonymous_principal(
    core_storage: Storage,
    tmp_path: Path,
) -> None:
    settings = Settings(STORAGE_DIR=str(tmp_path), REPLAYD_API_TOKEN=None)
    verifier = OidcVerifier(settings)
    request = Request({"type": "http", "method": "GET", "path": "/api/runs", "headers": []})

    principal = await resolve_principal(request, core_storage, settings, verifier)

    assert principal == Principal(kind="anonymous", user_id=None)
    assert auth_configured(settings) is False


@pytest.mark.asyncio
async def test_dev_mode_allows_unauthenticated_api_access(
    core_storage: Storage,
    tmp_path: Path,
) -> None:
    settings = Settings(STORAGE_DIR=str(tmp_path), REPLAYD_API_TOKEN=None)
    verifier = OidcVerifier(settings)
    client, app = _management_client(core_storage, settings, verifier)

    async with app.router.lifespan_context(app):
        async with client:
            response = await client.get("/api/runs")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_missing_credentials_returns_401_when_oidc_configured(
    core_storage: Storage,
    rsa_keypair: tuple[object, object],
    tmp_path: Path,
) -> None:
    _private_key, public_key = rsa_keypair
    settings = _oidc_settings(tmp_path)
    verifier = _verifier_for_public_key(settings, public_key)
    request = Request({"type": "http", "method": "GET", "path": "/api/runs", "headers": []})

    with pytest.raises(AuthenticationError):
        await resolve_principal(request, core_storage, settings, verifier)


def test_oidc_enabled_when_issuer_set(tmp_path: Path) -> None:
    settings = _oidc_settings(tmp_path)
    assert oidc_configured(settings) is True


def test_resolve_jwks_url_prefers_explicit_url_over_issuer_derivation(
    tmp_path: Path,
) -> None:
    settings = Settings(
        STORAGE_DIR=str(tmp_path),
        OIDC_ISSUER="http://localhost:3001/oidc",
        OIDC_JWKS_URL="http://logto:3001/oidc/jwks",
    )
    assert resolve_jwks_url(settings) == "http://logto:3001/oidc/jwks"


def test_resolve_jwks_url_derives_from_issuer_when_jwks_url_unset(
    tmp_path: Path,
) -> None:
    settings = Settings(
        STORAGE_DIR=str(tmp_path),
        OIDC_ISSUER="http://localhost:3001/oidc",
    )
    assert (
        resolve_jwks_url(settings)
        == "http://localhost:3001/oidc/.well-known/jwks.json"
    )


def test_verifier_uses_oidc_jwks_url_when_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        STORAGE_DIR=str(tmp_path),
        OIDC_ISSUER=TEST_ISSUER,
        OIDC_AUDIENCE=TEST_AUDIENCE,
        OIDC_JWKS_URL="http://logto:3001/oidc/jwks",
    )
    captured: dict[str, str] = {}

    class FakePyJWKClient:
        def __init__(self, url: str) -> None:
            captured["url"] = url

        def get_signing_key_from_jwt(self, token: str) -> object:
            del token
            raise OidcAuthError("not used in this test")

    monkeypatch.setattr("replayd.auth.oidc.PyJWKClient", FakePyJWKClient)
    OidcVerifier(settings)

    assert captured["url"] == "http://logto:3001/oidc/jwks"


@pytest.mark.asyncio
async def test_verify_oidc_connectivity_with_mock_http_client(
    tmp_path: Path,
) -> None:
    settings = Settings(
        STORAGE_DIR=str(tmp_path),
        OIDC_ISSUER=TEST_ISSUER,
        OIDC_AUDIENCE=TEST_AUDIENCE,
        OIDC_JWKS_URL="http://logto:3001/oidc/jwks",
    )

    class MockClient:
        async def get(self, url: str) -> object:
            request = httpx.Request("GET", url)
            if url.endswith("/.well-known/openid-configuration"):
                return httpx.Response(
                    200,
                    json={"issuer": TEST_ISSUER},
                    request=request,
                )
            if url.endswith("/oidc/jwks"):
                return httpx.Response(
                    200,
                    json={"keys": [{"kid": TEST_KID, "kty": "RSA"}]},
                    request=request,
                )
            raise AssertionError(f"unexpected url {url}")

        async def aclose(self) -> None:
            return None

    result = await verify_oidc_connectivity(settings, client=MockClient())
    assert result["status"] == "ok"
    assert result["jwks_key_count"] == 1


@pytest.mark.asyncio
async def test_health_oidc_skipped_when_oidc_not_configured(
    core_storage: Storage,
    tmp_path: Path,
) -> None:
    settings = Settings(STORAGE_DIR=str(tmp_path), REPLAYD_API_TOKEN=None)
    verifier = OidcVerifier(settings)
    client, app = _management_client(core_storage, settings, verifier)

    async with app.router.lifespan_context(app):
        async with client:
            response = await client.get("/health/oidc")

    assert response.status_code == 200
    assert response.json()["status"] == "skipped"


@pytest.mark.asyncio
async def test_verify_oidc_connectivity_raises_on_http_error(tmp_path: Path) -> None:
    settings = Settings(
        STORAGE_DIR=str(tmp_path),
        OIDC_ISSUER=TEST_ISSUER,
        OIDC_AUDIENCE=TEST_AUDIENCE,
        OIDC_JWKS_URL="http://logto:3001/oidc/jwks",
    )

    class FailingClient:
        async def get(self, url: str) -> object:
            del url
            raise httpx.ConnectError("connection refused")

        async def aclose(self) -> None:
            return None

    with pytest.raises(OidcConnectivityError):
        await verify_oidc_connectivity(settings, client=FailingClient())
