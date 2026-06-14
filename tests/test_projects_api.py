"""Project management API tests."""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pytest

from replayd.auth.principal import provision_user_principal
from replayd.auth.tenancy import resolve_accessible_project_ids
from replayd.config import Settings
from replayd.management import create_management_app
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


async def _provision_user(
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
    project_ids = await resolve_accessible_project_ids(storage, principal)
    assert len(project_ids) == 1
    return principal.user_id, project_ids[0]


@pytest.mark.asyncio
async def test_user_lists_and_creates_projects(
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

    subject = f"projects-user-{uuid.uuid4().hex[:8]}"
    _, default_project_id = await _provision_user(
        core_storage,
        subject=subject,
        email="projects@example.com",
    )
    token = _mint_jwt(private_key, sub=subject, email="projects@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    async with app.router.lifespan_context(app):
        async with client:
            initial_list = await client.get("/api/projects", headers=headers)
            create_resp = await client.post(
                "/api/projects",
                json={"name": "Staging"},
                headers=headers,
            )
            final_list = await client.get("/api/projects", headers=headers)

    assert initial_list.status_code == 200
    initial_payload = initial_list.json()
    assert initial_payload["total"] == 1
    assert initial_payload["items"][0]["id"] == default_project_id
    assert initial_payload["items"][0]["is_default"] is True

    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["name"] == "Staging"
    assert created["slug"] == "staging"
    assert created["is_default"] is False
    assert created["organization_id"]

    assert final_list.status_code == 200
    final_payload = final_list.json()
    assert final_payload["total"] == 2
    project_ids = {item["id"] for item in final_payload["items"]}
    assert default_project_id in project_ids
    assert created["id"] in project_ids

    accessible = await resolve_accessible_project_ids(
        core_storage,
        await provision_user_principal(
            core_storage,
            subject=subject,
            email="projects@example.com",
            name="Projects",
        ),
    )
    assert set(accessible) == project_ids


@pytest.mark.asyncio
async def test_user_renames_accessible_project(
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

    subject = f"rename-user-{uuid.uuid4().hex[:8]}"
    await _provision_user(core_storage, subject=subject, email="rename@example.com")
    token = _mint_jwt(private_key, sub=subject, email="rename@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    async with app.router.lifespan_context(app):
        async with client:
            create_resp = await client.post(
                "/api/projects",
                json={"name": "Production"},
                headers=headers,
            )
            project_id = create_resp.json()["id"]
            rename_resp = await client.patch(
                f"/api/projects/{project_id}",
                json={"name": "Production EU"},
                headers=headers,
            )
            list_resp = await client.get("/api/projects", headers=headers)

    assert rename_resp.status_code == 200
    renamed = rename_resp.json()
    assert renamed["id"] == project_id
    assert renamed["name"] == "Production EU"
    assert renamed["slug"] == "production-eu"

    listed = next(item for item in list_resp.json()["items"] if item["id"] == project_id)
    assert listed["name"] == "Production EU"


@pytest.mark.asyncio
async def test_user_cannot_rename_other_users_project(
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

    subject_a = f"projects-a-{uuid.uuid4().hex[:8]}"
    subject_b = f"projects-b-{uuid.uuid4().hex[:8]}"
    _, project_a = await _provision_user(
        core_storage,
        subject=subject_a,
        email="a@example.com",
    )
    await _provision_user(core_storage, subject=subject_b, email="b@example.com")

    token_b = _mint_jwt(private_key, sub=subject_b, email="b@example.com")
    headers_b = {"Authorization": f"Bearer {token_b}"}

    async with app.router.lifespan_context(app):
        async with client:
            list_b = await client.get("/api/projects", headers=headers_b)
            rename_b = await client.patch(
                f"/api/projects/{project_a}",
                json={"name": "Stolen"},
                headers=headers_b,
            )

    assert list_b.status_code == 200
    assert list_b.json()["total"] == 1
    assert list_b.json()["items"][0]["id"] != project_a

    assert rename_b.status_code == 404
