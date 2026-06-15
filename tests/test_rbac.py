"""Role-based access control tests for mutating control-plane endpoints."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest

from replayd.storage.base import Storage
from test_invitations import _add_org_member_before_login, _provision_owner
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


@dataclass
class RbacOrg:
    org_id: str
    owner_user_id: str
    owner_subject: str
    owner_email: str
    admin_subject: str
    admin_email: str
    member_subject: str
    member_email: str
    viewer_subject: str
    viewer_email: str
    removable_member_user_id: str
    default_project_id: str


async def _setup_rbac_org(storage: Storage) -> RbacOrg:
    owner_subject = f"rbac-owner-{uuid.uuid4().hex[:8]}"
    owner_email = f"rbac-owner-{uuid.uuid4().hex[:6]}@example.com"
    owner_user_id, org_id = await _provision_owner(
        storage,
        subject=owner_subject,
        email=owner_email,
    )

    admin_subject = f"rbac-admin-{uuid.uuid4().hex[:8]}"
    admin_email = f"rbac-admin-{uuid.uuid4().hex[:6]}@example.com"
    await _add_org_member_before_login(
        storage,
        org_id=org_id,
        subject=admin_subject,
        email=admin_email,
        role="admin",
    )

    member_subject = f"rbac-member-{uuid.uuid4().hex[:8]}"
    member_email = f"rbac-member-{uuid.uuid4().hex[:6]}@example.com"
    await _add_org_member_before_login(
        storage,
        org_id=org_id,
        subject=member_subject,
        email=member_email,
        role="member",
    )

    viewer_subject = f"rbac-viewer-{uuid.uuid4().hex[:8]}"
    viewer_email = f"rbac-viewer-{uuid.uuid4().hex[:6]}@example.com"
    await _add_org_member_before_login(
        storage,
        org_id=org_id,
        subject=viewer_subject,
        email=viewer_email,
        role="viewer",
    )

    removable = await _add_org_member_before_login(
        storage,
        org_id=org_id,
        subject=f"rbac-removable-{uuid.uuid4().hex[:8]}",
        email=f"rbac-removable-{uuid.uuid4().hex[:6]}@example.com",
        role="member",
    )

    projects = await storage.list_accessible_projects(owner_user_id)
    assert len(projects) >= 1

    return RbacOrg(
        org_id=org_id,
        owner_user_id=owner_user_id,
        owner_subject=owner_subject,
        owner_email=owner_email,
        admin_subject=admin_subject,
        admin_email=admin_email,
        member_subject=member_subject,
        member_email=member_email,
        viewer_subject=viewer_subject,
        viewer_email=viewer_email,
        removable_member_user_id=removable.id,
        default_project_id=projects[0].id,
    )


def _headers(
    private_key: object,
    *,
    subject: str,
    email: str,
) -> dict[str, str]:
    token = _mint_jwt(
        private_key,
        sub=subject,
        email=email,
        email_verified=True,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_viewer_cannot_mutate(
    core_storage: Storage,
    rsa_keypair: tuple[object, object],
    tmp_path: Path,
) -> None:
    private_key, public_key = rsa_keypair
    org = await _setup_rbac_org(core_storage)
    settings = _oidc_settings(tmp_path)
    client, app = _management_client(
        core_storage,
        settings,
        _verifier_for_public_key(settings, public_key),
    )
    headers = _headers(
        private_key,
        subject=org.viewer_subject,
        email=org.viewer_email,
    )

    async with app.router.lifespan_context(app):
        async with client:
            await client.get("/api/runs", headers=headers)
            invite = await client.post(
                "/api/invitations",
                json={"email": "viewer-invite@example.com"},
                headers=headers,
            )
            project = await client.post(
                "/api/projects",
                json={"name": "Viewer project"},
                headers=headers,
            )
            key = await client.post(
                "/api/ingest-keys",
                json={"name": "viewer-key"},
                headers=headers,
            )

    assert invite.status_code == 403
    assert project.status_code == 403
    assert key.status_code == 403


@pytest.mark.asyncio
async def test_member_can_create_project_and_key_but_not_invite_or_remove(
    core_storage: Storage,
    rsa_keypair: tuple[object, object],
    tmp_path: Path,
) -> None:
    private_key, public_key = rsa_keypair
    org = await _setup_rbac_org(core_storage)
    settings = _oidc_settings(tmp_path)
    client, app = _management_client(
        core_storage,
        settings,
        _verifier_for_public_key(settings, public_key),
    )
    headers = _headers(
        private_key,
        subject=org.member_subject,
        email=org.member_email,
    )

    async with app.router.lifespan_context(app):
        async with client:
            await client.get("/api/runs", headers=headers)
            invite = await client.post(
                "/api/invitations",
                json={"email": "member-invite@example.com"},
                headers=headers,
            )
            project = await client.post(
                "/api/projects",
                json={"name": "Member project"},
                headers=headers,
            )
            key = await client.post(
                "/api/ingest-keys",
                json={"name": "member-key", "project_id": org.default_project_id},
                headers=headers,
            )
            remove_owner = await client.delete(
                f"/api/members/{org.owner_user_id}",
                headers=headers,
            )

    assert invite.status_code == 403
    assert project.status_code == 201
    assert key.status_code == 201
    assert remove_owner.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_invite_and_remove_member_but_not_owner(
    core_storage: Storage,
    rsa_keypair: tuple[object, object],
    tmp_path: Path,
) -> None:
    private_key, public_key = rsa_keypair
    org = await _setup_rbac_org(core_storage)
    settings = _oidc_settings(tmp_path)
    client, app = _management_client(
        core_storage,
        settings,
        _verifier_for_public_key(settings, public_key),
    )
    headers = _headers(
        private_key,
        subject=org.admin_subject,
        email=org.admin_email,
    )

    async with app.router.lifespan_context(app):
        async with client:
            await client.get("/api/runs", headers=headers)
            invite = await client.post(
                "/api/invitations",
                json={"email": "admin-invite@example.com"},
                headers=headers,
            )
            remove_member = await client.delete(
                f"/api/members/{org.removable_member_user_id}",
                headers=headers,
            )
            remove_owner = await client.delete(
                f"/api/members/{org.owner_user_id}",
                headers=headers,
            )

    assert invite.status_code == 201
    assert remove_member.status_code == 204
    assert remove_owner.status_code == 403


@pytest.mark.asyncio
async def test_owner_can_perform_all_mutating_actions(
    core_storage: Storage,
    rsa_keypair: tuple[object, object],
    tmp_path: Path,
) -> None:
    private_key, public_key = rsa_keypair
    org = await _setup_rbac_org(core_storage)
    settings = _oidc_settings(tmp_path)
    client, app = _management_client(
        core_storage,
        settings,
        _verifier_for_public_key(settings, public_key),
    )
    headers = _headers(
        private_key,
        subject=org.owner_subject,
        email=org.owner_email,
    )

    async with app.router.lifespan_context(app):
        async with client:
            invite = await client.post(
                "/api/invitations",
                json={"email": "owner-invite@example.com"},
                headers=headers,
            )
            project = await client.post(
                "/api/projects",
                json={"name": "Owner project"},
                headers=headers,
            )
            key = await client.post(
                "/api/ingest-keys",
                json={"name": "owner-key", "project_id": org.default_project_id},
                headers=headers,
            )
            remove_member = await client.delete(
                f"/api/members/{org.removable_member_user_id}",
                headers=headers,
            )

    assert invite.status_code == 201
    assert project.status_code == 201
    assert key.status_code == 201
    assert remove_member.status_code == 204
