"""GET /api/me profile tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from replayd.auth.principal import provision_user_principal
from replayd.config import Settings
from replayd.management import create_management_app
from replayd.models import Membership, Organization
from replayd.storage.base import Storage
from test_oidc import (
    _generate_rsa_keypair,
    _management_client,
    _mint_jwt,
    _oidc_settings,
    _verifier_for_public_key,
)


def _now() -> datetime:
    return datetime(2026, 6, 13, 12, 0, 0, tzinfo=UTC)


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


@pytest.mark.asyncio
async def test_authenticated_user_gets_profile_with_memberships(
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

    subject = f"me-user-{uuid.uuid4().hex[:8]}"
    email = f"me-user-{uuid.uuid4().hex[:6]}@example.com"
    principal = await provision_user_principal(
        core_storage,
        subject=subject,
        email=email,
        name="Me User",
    )
    assert principal.user_id is not None
    memberships = await core_storage.list_memberships_for_user(principal.user_id)
    assert len(memberships) == 1
    org = await core_storage.get_organization(memberships[0].org_id)
    assert org is not None

    token = _mint_jwt(
        private_key,
        sub=subject,
        email=email,
        name="Me User",
        email_verified=True,
    )
    headers = {"Authorization": f"Bearer {token}"}

    async with app.router.lifespan_context(app):
        async with client:
            response = await client.get("/api/me", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "user"
    assert payload["user_id"] == principal.user_id
    assert payload["email"] == email
    assert payload["email_verified"] is True
    assert payload["name"] == "Me User"
    assert "created_at" in payload
    assert len(payload["memberships"]) == 1
    membership = payload["memberships"][0]
    assert membership["organization_id"] == org.id
    assert membership["organization_name"] == org.name
    assert membership["role"] == "owner"
    assert membership["is_primary"] is True


@pytest.mark.asyncio
async def test_is_primary_marks_earliest_membership(
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

    subject = f"me-primary-{uuid.uuid4().hex[:8]}"
    email = f"me-primary-{uuid.uuid4().hex[:6]}@example.com"
    principal = await provision_user_principal(
        core_storage,
        subject=subject,
        email=email,
        name=None,
    )
    assert principal.user_id is not None

    primary_membership = min(
        await core_storage.list_memberships_for_user(principal.user_id),
        key=lambda membership: membership.created_at,
    )
    secondary_org = Organization(
        id=f"org-secondary-{uuid.uuid4().hex[:8]}",
        name="Secondary Org",
        slug=f"secondary-{uuid.uuid4().hex[:8]}",
        created_at=primary_membership.created_at + timedelta(days=1),
    )
    await core_storage.create_organization(secondary_org)
    await core_storage.create_membership(
        Membership(
            id=f"membership-secondary-{uuid.uuid4().hex[:8]}",
            org_id=secondary_org.id,
            user_id=principal.user_id,
            role="member",
            created_at=primary_membership.created_at + timedelta(days=1),
        )
    )

    token = _mint_jwt(private_key, sub=subject, email=email, email_verified=True)
    headers = {"Authorization": f"Bearer {token}"}

    async with app.router.lifespan_context(app):
        async with client:
            response = await client.get("/api/me", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["memberships"]) == 2
    primary = next(item for item in payload["memberships"] if item["is_primary"])
    secondary = next(item for item in payload["memberships"] if not item["is_primary"])
    assert primary["organization_id"] == primary_membership.org_id
    assert primary["role"] == "owner"
    assert secondary["organization_id"] == secondary_org.id
    assert secondary["role"] == "member"


@pytest.mark.asyncio
async def test_anonymous_gets_anonymous_shape(
    core_storage: Storage,
    tmp_path: Path,
) -> None:
    client, app = _unscoped_client(core_storage, tmp_path)

    async with app.router.lifespan_context(app):
        async with client:
            response = await client.get("/api/me")

    assert response.status_code == 200
    assert response.json() == {"kind": "anonymous"}


@pytest.mark.asyncio
async def test_each_user_sees_their_own_profile(
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

    subject_a = f"me-a-{uuid.uuid4().hex[:8]}"
    subject_b = f"me-b-{uuid.uuid4().hex[:8]}"
    email_a = f"me-a-{uuid.uuid4().hex[:6]}@example.com"
    email_b = f"me-b-{uuid.uuid4().hex[:6]}@example.com"
    user_a = await provision_user_principal(
        core_storage,
        subject=subject_a,
        email=email_a,
        name="User A",
    )
    user_b = await provision_user_principal(
        core_storage,
        subject=subject_b,
        email=email_b,
        name="User B",
    )

    token_a = _mint_jwt(private_key, sub=subject_a, email=email_a, email_verified=True)
    token_b = _mint_jwt(private_key, sub=subject_b, email=email_b, email_verified=True)

    async with app.router.lifespan_context(app):
        async with client:
            response_a = await client.get(
                "/api/me",
                headers={"Authorization": f"Bearer {token_a}"},
            )
            response_b = await client.get(
                "/api/me",
                headers={"Authorization": f"Bearer {token_b}"},
            )

    assert response_a.status_code == 200
    assert response_b.status_code == 200
    payload_a = response_a.json()
    payload_b = response_b.json()
    assert payload_a["user_id"] == user_a.user_id
    assert payload_b["user_id"] == user_b.user_id
    assert payload_a["email"] == email_a
    assert payload_b["email"] == email_b
    assert payload_a["user_id"] != payload_b["user_id"]
