"""Team invitation and org membership API tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from replayd.auth.principal import provision_user_principal
from replayd.models import Membership, User
from replayd.storage.base import Storage
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


async def _provision_owner(
    storage: Storage,
    *,
    subject: str,
    email: str,
) -> tuple[str, str]:
    principal = await provision_user_principal(
        storage,
        subject=subject,
        email=email,
        name=email.split("@")[0].title(),
    )
    assert principal.user_id is not None
    memberships = await storage.list_memberships_for_user(principal.user_id)
    assert len(memberships) == 1
    return principal.user_id, memberships[0].org_id


async def _accept_incoming_invitation(client, headers: dict[str, str]) -> str:
    incoming_resp = await client.get("/api/invitations/incoming", headers=headers)
    assert incoming_resp.status_code == 200
    items = incoming_resp.json()["items"]
    assert len(items) == 1
    invitation_id = items[0]["id"]
    accept_resp = await client.post(
        f"/api/invitations/{invitation_id}/accept",
        headers=headers,
    )
    assert accept_resp.status_code == 204
    return invitation_id


@pytest.mark.asyncio
async def test_invitee_sees_pending_invite_and_accepts_to_join(
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

    owner_subject = f"invite-owner-{uuid.uuid4().hex[:8]}"
    owner_email = f"owner-{uuid.uuid4().hex[:6]}@example.com"
    invitee_email = f"invitee-{uuid.uuid4().hex[:6]}@example.com"
    await _provision_owner(core_storage, subject=owner_subject, email=owner_email)

    owner_token = _mint_jwt(
        private_key,
        sub=owner_subject,
        email=owner_email,
        email_verified=True,
    )
    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    async with app.router.lifespan_context(app):
        async with client:
            create_resp = await client.post(
                "/api/invitations",
                json={"email": invitee_email, "role": "member"},
                headers=owner_headers,
            )
            list_resp = await client.get("/api/invitations", headers=owner_headers)

            assert create_resp.status_code == 201
            created = create_resp.json()
            assert created["email"] == invitee_email.lower()
            assert created["status"] == "pending"
            assert created["role"] == "member"

            assert list_resp.status_code == 200
            assert list_resp.json()["total"] == 1
            assert list_resp.json()["items"][0]["id"] == created["id"]

            invitee_subject = f"invitee-{uuid.uuid4().hex[:8]}"
            invitee_token = _mint_jwt(
                private_key,
                sub=invitee_subject,
                email=invitee_email,
                email_verified=True,
            )
            invitee_headers = {"Authorization": f"Bearer {invitee_token}"}
            await client.get("/api/runs", headers=invitee_headers)

            incoming_resp = await client.get(
                "/api/invitations/incoming",
                headers=invitee_headers,
            )
            members_before = await client.get("/api/members", headers=owner_headers)

            assert incoming_resp.status_code == 200
            incoming = incoming_resp.json()
            assert incoming["total"] == 1
            assert incoming["items"][0]["id"] == created["id"]
            assert incoming["items"][0]["role"] == "member"
            assert incoming["items"][0]["invited_by"] == owner_email

            member_emails_before = {
                item["email"] for item in members_before.json()["items"]
            }
            assert invitee_email.lower() not in member_emails_before

            await _accept_incoming_invitation(client, invitee_headers)

            members_after = await client.get("/api/members", headers=owner_headers)
            incoming_after = await client.get(
                "/api/invitations/incoming",
                headers=invitee_headers,
            )
            owner_pending = await client.get("/api/invitations", headers=owner_headers)

    member_emails_after = {item["email"] for item in members_after.json()["items"]}
    assert owner_email in member_emails_after
    assert invitee_email.lower() in member_emails_after
    assert incoming_after.status_code == 200
    assert incoming_after.json()["total"] == 0
    assert owner_pending.status_code == 200
    assert owner_pending.json()["total"] == 0


@pytest.mark.asyncio
async def test_revoke_removes_pending_invitation(
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

    owner_subject = f"revoke-owner-{uuid.uuid4().hex[:8]}"
    owner_email = f"revoke-owner-{uuid.uuid4().hex[:6]}@example.com"
    await _provision_owner(core_storage, subject=owner_subject, email=owner_email)
    owner_token = _mint_jwt(
        private_key,
        sub=owner_subject,
        email=owner_email,
        email_verified=True,
    )
    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    async with app.router.lifespan_context(app):
        async with client:
            create_resp = await client.post(
                "/api/invitations",
                json={"email": "revoke-me@example.com"},
                headers=owner_headers,
            )
            invitation_id = create_resp.json()["id"]
            revoke_resp = await client.delete(
                f"/api/invitations/{invitation_id}",
                headers=owner_headers,
            )
            list_resp = await client.get("/api/invitations", headers=owner_headers)

    assert create_resp.status_code == 201
    assert revoke_resp.status_code == 204
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_other_org_cannot_list_or_revoke_invitations(
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
    await _provision_owner(core_storage, subject=owner_a_subject, email=owner_a_email)
    await _provision_owner(core_storage, subject=owner_b_subject, email=owner_b_email)

    owner_a_token = _mint_jwt(
        private_key,
        sub=owner_a_subject,
        email=owner_a_email,
        email_verified=True,
    )
    owner_b_token = _mint_jwt(
        private_key,
        sub=owner_b_subject,
        email=owner_b_email,
        email_verified=True,
    )
    headers_a = {"Authorization": f"Bearer {owner_a_token}"}
    headers_b = {"Authorization": f"Bearer {owner_b_token}"}

    async with app.router.lifespan_context(app):
        async with client:
            create_resp = await client.post(
                "/api/invitations",
                json={"email": "secret-invite@example.com"},
                headers=headers_a,
            )
            invitation_id = create_resp.json()["id"]
            list_b = await client.get("/api/invitations", headers=headers_b)
            revoke_b = await client.delete(
                f"/api/invitations/{invitation_id}",
                headers=headers_b,
            )
            list_a = await client.get("/api/invitations", headers=headers_a)

    assert create_resp.status_code == 201
    assert list_b.status_code == 200
    assert list_b.json()["total"] == 0
    assert revoke_b.status_code == 404
    assert list_a.status_code == 200
    assert list_a.json()["total"] == 1


@pytest.mark.asyncio
async def test_accept_invitation_is_idempotent(
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

    owner_subject = f"idempotent-owner-{uuid.uuid4().hex[:8]}"
    owner_email = f"idempotent-owner-{uuid.uuid4().hex[:6]}@example.com"
    owner_user_id, org_id = await _provision_owner(
        core_storage,
        subject=owner_subject,
        email=owner_email,
    )

    invitee_email = f"idempotent-invitee-{uuid.uuid4().hex[:6]}@example.com"
    invitation = await core_storage.create_invitation(
        org_id=org_id,
        email=invitee_email,
        role="member",
        invited_by_user_id=owner_user_id,
    )

    invitee_subject = f"idempotent-invitee-{uuid.uuid4().hex[:8]}"
    invitee_token = _mint_jwt(
        private_key,
        sub=invitee_subject,
        email=invitee_email,
        email_verified=True,
    )
    invitee_headers = {"Authorization": f"Bearer {invitee_token}"}

    async with app.router.lifespan_context(app):
        async with client:
            await client.get("/api/runs", headers=invitee_headers)
            first = await client.post(
                f"/api/invitations/{invitation.id}/accept",
                headers=invitee_headers,
            )
            second = await client.post(
                f"/api/invitations/{invitation.id}/accept",
                headers=invitee_headers,
            )

    assert first.status_code == 204
    assert second.status_code == 204

    invitee_user = await core_storage.get_user_by_subject(invitee_subject)
    assert invitee_user is not None
    memberships = await core_storage.list_memberships_for_user(invitee_user.id)
    org_memberships = [item for item in memberships if item.org_id == org_id]
    assert len(org_memberships) == 1

    stored_invite = await core_storage.get_invitation(invitation.id)
    assert stored_invite is not None
    assert stored_invite.status == "accepted"


@pytest.mark.asyncio
async def test_unverified_email_sees_no_incoming_invitations(
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

    owner_subject = f"unverified-owner-{uuid.uuid4().hex[:8]}"
    owner_email = f"unverified-owner-{uuid.uuid4().hex[:6]}@example.com"
    owner_user_id, org_id = await _provision_owner(
        core_storage,
        subject=owner_subject,
        email=owner_email,
    )

    invitee_email = f"unverified-invitee-{uuid.uuid4().hex[:6]}@example.com"
    invitation = await core_storage.create_invitation(
        org_id=org_id,
        email=invitee_email,
        role="member",
        invited_by_user_id=owner_user_id,
    )

    invitee_subject = f"unverified-invitee-{uuid.uuid4().hex[:8]}"
    invitee_token = _mint_jwt(
        private_key,
        sub=invitee_subject,
        email=invitee_email,
        email_verified=False,
    )
    invitee_headers = {"Authorization": f"Bearer {invitee_token}"}

    async with app.router.lifespan_context(app):
        async with client:
            await client.get("/api/runs", headers=invitee_headers)
            incoming_resp = await client.get(
                "/api/invitations/incoming",
                headers=invitee_headers,
            )
            accept_resp = await client.post(
                f"/api/invitations/{invitation.id}/accept",
                headers=invitee_headers,
            )

    assert incoming_resp.status_code == 200
    assert incoming_resp.json()["total"] == 0
    assert accept_resp.status_code == 403

    invitee_user = await core_storage.get_user_by_subject(invitee_subject)
    assert invitee_user is not None
    memberships = await core_storage.list_memberships_for_user(invitee_user.id)
    invited_memberships = [item for item in memberships if item.org_id == org_id]
    assert invited_memberships == []

    pending = await core_storage.list_invitations(org_id, status="pending")
    assert len(pending) == 1


@pytest.mark.asyncio
async def test_invitee_declines_invitation(
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

    owner_subject = f"decline-owner-{uuid.uuid4().hex[:8]}"
    owner_email = f"decline-owner-{uuid.uuid4().hex[:6]}@example.com"
    owner_user_id, org_id = await _provision_owner(
        core_storage,
        subject=owner_subject,
        email=owner_email,
    )

    invitee_email = f"decline-invitee-{uuid.uuid4().hex[:6]}@example.com"
    invitation = await core_storage.create_invitation(
        org_id=org_id,
        email=invitee_email,
        role="member",
        invited_by_user_id=owner_user_id,
    )

    invitee_subject = f"decline-invitee-{uuid.uuid4().hex[:8]}"
    invitee_token = _mint_jwt(
        private_key,
        sub=invitee_subject,
        email=invitee_email,
        email_verified=True,
    )
    invitee_headers = {"Authorization": f"Bearer {invitee_token}"}
    owner_token = _mint_jwt(
        private_key,
        sub=owner_subject,
        email=owner_email,
        email_verified=True,
    )
    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    async with app.router.lifespan_context(app):
        async with client:
            await client.get("/api/runs", headers=invitee_headers)
            decline_resp = await client.post(
                f"/api/invitations/{invitation.id}/decline",
                headers=invitee_headers,
            )
            incoming_resp = await client.get(
                "/api/invitations/incoming",
                headers=invitee_headers,
            )
            members_resp = await client.get("/api/members", headers=owner_headers)
            owner_pending = await client.get("/api/invitations", headers=owner_headers)

    assert decline_resp.status_code == 204
    assert incoming_resp.status_code == 200
    assert incoming_resp.json()["total"] == 0
    assert members_resp.status_code == 200
    member_emails = {item["email"] for item in members_resp.json()["items"]}
    assert invitee_email.lower() not in member_emails
    assert owner_pending.status_code == 200
    assert owner_pending.json()["total"] == 0

    stored_invite = await core_storage.get_invitation(invitation.id)
    assert stored_invite is not None
    assert stored_invite.status == "declined"


@pytest.mark.asyncio
async def test_cannot_accept_or_decline_invite_for_different_email(
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

    owner_subject = f"wrong-email-owner-{uuid.uuid4().hex[:8]}"
    owner_email = f"wrong-email-owner-{uuid.uuid4().hex[:6]}@example.com"
    owner_user_id, org_id = await _provision_owner(
        core_storage,
        subject=owner_subject,
        email=owner_email,
    )

    invited_email = f"invited-{uuid.uuid4().hex[:6]}@example.com"
    invitation = await core_storage.create_invitation(
        org_id=org_id,
        email=invited_email,
        role="member",
        invited_by_user_id=owner_user_id,
    )

    other_subject = f"other-user-{uuid.uuid4().hex[:8]}"
    other_email = f"other-user-{uuid.uuid4().hex[:6]}@example.com"
    other_token = _mint_jwt(
        private_key,
        sub=other_subject,
        email=other_email,
        email_verified=True,
    )
    other_headers = {"Authorization": f"Bearer {other_token}"}

    async with app.router.lifespan_context(app):
        async with client:
            await client.get("/api/runs", headers=other_headers)
            accept_resp = await client.post(
                f"/api/invitations/{invitation.id}/accept",
                headers=other_headers,
            )
            decline_resp = await client.post(
                f"/api/invitations/{invitation.id}/decline",
                headers=other_headers,
            )

    assert accept_resp.status_code == 403
    assert decline_resp.status_code == 403

    stored_invite = await core_storage.get_invitation(invitation.id)
    assert stored_invite is not None
    assert stored_invite.status == "pending"


async def _add_org_member_before_login(
    storage: Storage,
    *,
    org_id: str,
    subject: str,
    email: str,
    role: str,
) -> User:
    user = User(
        id=f"user-{uuid.uuid4().hex[:8]}",
        email=email,
        subject=subject,
        name=email.split("@")[0].title(),
        created_at=datetime.now(UTC),
    )
    await storage.create_user(user)
    await storage.create_membership(
        Membership(
            id=f"membership-{uuid.uuid4().hex[:8]}",
            org_id=org_id,
            user_id=user.id,
            role=role,
            created_at=datetime.now(UTC),
        )
    )
    return user
