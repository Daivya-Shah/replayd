"""Organization member removal API tests."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from replayd.storage.base import Storage
from test_invitations import _provision_owner
from test_oidc import (
    _generate_rsa_keypair,
    _management_client,
    _mint_jwt,
    _oidc_settings,
    _verifier_for_public_key,
)


@pytest.fixture
def rsa_keypair() -> tuple[object, object]:
    return _generate_rsa_keypair()


@pytest.mark.asyncio
async def test_owner_removes_member(
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

    owner_subject = f"remove-owner-{uuid.uuid4().hex[:8]}"
    owner_email = f"remove-owner-{uuid.uuid4().hex[:6]}@example.com"
    owner_user_id, _ = await _provision_owner(
        core_storage,
        subject=owner_subject,
        email=owner_email,
    )
    owner_token = _mint_jwt(
        private_key,
        sub=owner_subject,
        email=owner_email,
        email_verified=True,
    )
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    invitee_email = f"remove-member-{uuid.uuid4().hex[:6]}@example.com"

    async with app.router.lifespan_context(app):
        async with client:
            invitee_subject = f"invitee-{uuid.uuid4().hex[:8]}"
            await client.post(
                "/api/invitations",
                json={"email": invitee_email, "role": "member"},
                headers=owner_headers,
            )
            invitee_token = _mint_jwt(
                private_key,
                sub=invitee_subject,
                email=invitee_email,
                email_verified=True,
            )
            await client.get("/api/runs", headers={"Authorization": f"Bearer {invitee_token}"})
            invitee_user = await core_storage.get_user_by_subject(invitee_subject)
            assert invitee_user is not None

            before = await client.get("/api/members", headers=owner_headers)
            remove_resp = await client.delete(
                f"/api/members/{invitee_user.id}",
                headers=owner_headers,
            )
            after = await client.get("/api/members", headers=owner_headers)

    assert before.status_code == 200
    assert before.json()["total"] == 2
    assert remove_resp.status_code == 204
    assert after.status_code == 200
    assert after.json()["total"] == 1
    remaining_ids = {item["email"] for item in after.json()["items"]}
    assert owner_email in remaining_ids
    assert invitee_email.lower() not in remaining_ids
    assert owner_user_id  # referenced so provisioning side effect is exercised


@pytest.mark.asyncio
async def test_cannot_remove_last_owner(
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

    owner_subject = f"last-owner-{uuid.uuid4().hex[:8]}"
    owner_email = f"last-owner-{uuid.uuid4().hex[:6]}@example.com"
    owner_user_id, _ = await _provision_owner(
        core_storage,
        subject=owner_subject,
        email=owner_email,
    )
    owner_token = _mint_jwt(
        private_key,
        sub=owner_subject,
        email=owner_email,
        email_verified=True,
    )
    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    async with app.router.lifespan_context(app):
        async with client:
            response = await client.delete(
                f"/api/members/{owner_user_id}",
                headers=owner_headers,
            )

    assert response.status_code == 409
    assert response.json()["detail"] == "cannot remove the last owner"


@pytest.mark.asyncio
async def test_member_cannot_remove_others(
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

    owner_subject = f"perm-owner-{uuid.uuid4().hex[:8]}"
    owner_email = f"perm-owner-{uuid.uuid4().hex[:6]}@example.com"
    owner_user_id, _ = await _provision_owner(
        core_storage,
        subject=owner_subject,
        email=owner_email,
    )
    owner_token = _mint_jwt(
        private_key,
        sub=owner_subject,
        email=owner_email,
        email_verified=True,
    )
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    invitee_email = f"perm-member-{uuid.uuid4().hex[:6]}@example.com"

    async with app.router.lifespan_context(app):
        async with client:
            await client.post(
                "/api/invitations",
                json={"email": invitee_email, "role": "member"},
                headers=owner_headers,
            )
            invitee_subject = f"invitee-{uuid.uuid4().hex[:8]}"
            invitee_token = _mint_jwt(
                private_key,
                sub=invitee_subject,
                email=invitee_email,
                email_verified=True,
            )
            member_headers = {"Authorization": f"Bearer {invitee_token}"}
            await client.get("/api/runs", headers=member_headers)
            response = await client.delete(
                f"/api/members/{owner_user_id}",
                headers=member_headers,
            )

    assert response.status_code == 403
    assert response.json()["detail"] == "forbidden"


@pytest.mark.asyncio
async def test_cannot_remove_member_from_other_org(
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

    owner_a_subject = f"org-a-{uuid.uuid4().hex[:8]}"
    owner_b_subject = f"org-b-{uuid.uuid4().hex[:8]}"
    owner_a_email = f"org-a-{uuid.uuid4().hex[:6]}@example.com"
    owner_b_email = f"org-b-{uuid.uuid4().hex[:6]}@example.com"
    _, _ = await _provision_owner(
        core_storage,
        subject=owner_a_subject,
        email=owner_a_email,
    )
    owner_b_user_id, _ = await _provision_owner(
        core_storage,
        subject=owner_b_subject,
        email=owner_b_email,
    )

    owner_a_token = _mint_jwt(
        private_key,
        sub=owner_a_subject,
        email=owner_a_email,
        email_verified=True,
    )
    headers_a = {"Authorization": f"Bearer {owner_a_token}"}

    async with app.router.lifespan_context(app):
        async with client:
            response = await client.delete(
                f"/api/members/{owner_b_user_id}",
                headers=headers_a,
            )

    assert response.status_code == 404
    assert response.json()["detail"] == "member not found"


@pytest.mark.asyncio
async def test_non_last_owner_can_remove_themselves(
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

    owner_a_subject = f"co-owner-a-{uuid.uuid4().hex[:8]}"
    owner_a_email = f"co-owner-a-{uuid.uuid4().hex[:6]}@example.com"
    owner_a_user_id, _ = await _provision_owner(
        core_storage,
        subject=owner_a_subject,
        email=owner_a_email,
    )

    owner_b_email = f"co-owner-b-{uuid.uuid4().hex[:6]}@example.com"
    owner_a_token = _mint_jwt(
        private_key,
        sub=owner_a_subject,
        email=owner_a_email,
        email_verified=True,
    )
    owner_a_headers = {"Authorization": f"Bearer {owner_a_token}"}

    async with app.router.lifespan_context(app):
        async with client:
            await client.post(
                "/api/invitations",
                json={"email": owner_b_email, "role": "owner"},
                headers=owner_a_headers,
            )
            owner_b_subject = f"co-owner-b-{uuid.uuid4().hex[:8]}"
            owner_b_token = _mint_jwt(
                private_key,
                sub=owner_b_subject,
                email=owner_b_email,
                email_verified=True,
            )
            owner_b_headers = {"Authorization": f"Bearer {owner_b_token}"}
            await client.get("/api/runs", headers=owner_b_headers)
            owner_b_user = await core_storage.get_user_by_subject(owner_b_subject)
            assert owner_b_user is not None

            remove_resp = await client.delete(
                f"/api/members/{owner_b_user.id}",
                headers=owner_b_headers,
            )
            members_resp = await client.get("/api/members", headers=owner_a_headers)

    assert remove_resp.status_code == 204
    assert members_resp.status_code == 200
    assert members_resp.json()["total"] == 1
    assert members_resp.json()["items"][0]["email"] == owner_a_email
    assert owner_a_user_id  # keep owner provisioned for org scoping
