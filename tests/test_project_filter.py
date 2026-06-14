"""Optional project_id filter tests for list and ingest-key endpoints."""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pytest

from replayd.auth.principal import provision_user_principal
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
from test_storage import _sample_exchange


@pytest.fixture
def rsa_keypair() -> tuple[object, object]:
    return _generate_rsa_keypair()


async def _provision_user_with_two_projects(
    storage: Storage,
    client: httpx.AsyncClient,
    headers: dict[str, str],
) -> tuple[str, str]:
    create_resp = await client.post(
        "/api/projects",
        json={"name": "Project B"},
        headers=headers,
    )
    assert create_resp.status_code == 201
    project_b = create_resp.json()["id"]

    list_resp = await client.get("/api/projects", headers=headers)
    assert list_resp.status_code == 200
    projects = list_resp.json()["items"]
    default_project = next(item for item in projects if item["is_default"])
    return default_project["id"], project_b


async def _seed_run(storage: Storage, *, run_id: str, project_id: str) -> None:
    await storage.save_exchange(
        _sample_exchange(
            exchange_id=f"exchange-{run_id}",
            run_id=run_id,
            project_id=project_id,
        )
    )


@pytest.mark.asyncio
async def test_list_runs_filters_by_project_id(
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

    subject = f"filter-runs-{uuid.uuid4().hex[:8]}"
    await provision_user_principal(
        core_storage,
        subject=subject,
        email="filter-runs@example.com",
        name="Filter Runs",
    )
    token = _mint_jwt(private_key, sub=subject, email="filter-runs@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    async with app.router.lifespan_context(app):
        async with client:
            project_a, project_b = await _provision_user_with_two_projects(
                core_storage,
                client,
                headers,
            )
            run_a = f"run-a-{uuid.uuid4().hex}"
            run_b = f"run-b-{uuid.uuid4().hex}"
            await _seed_run(core_storage, run_id=run_a, project_id=project_a)
            await _seed_run(core_storage, run_id=run_b, project_id=project_b)

            all_runs = await client.get("/api/runs", headers=headers)
            runs_a = await client.get("/api/runs", params={"project_id": project_a}, headers=headers)
            runs_b = await client.get("/api/runs", params={"project_id": project_b}, headers=headers)
            other_user_subject = f"other-{uuid.uuid4().hex[:8]}"
            await provision_user_principal(
                core_storage,
                subject=other_user_subject,
                email="other@example.com",
                name="Other",
            )
            other_token = _mint_jwt(
                private_key,
                sub=other_user_subject,
                email="other@example.com",
            )
            denied = await client.get(
                "/api/runs",
                params={"project_id": project_a},
                headers={"Authorization": f"Bearer {other_token}"},
            )

    assert all_runs.status_code == 200
    all_run_ids = {item["run_id"] for item in all_runs.json()["items"]}
    assert all_run_ids == {run_a, run_b}

    assert runs_a.status_code == 200
    assert runs_a.json()["total"] == 1
    assert runs_a.json()["items"][0]["run_id"] == run_a

    assert runs_b.status_code == 200
    assert runs_b.json()["total"] == 1
    assert runs_b.json()["items"][0]["run_id"] == run_b

    assert denied.status_code == 404


@pytest.mark.asyncio
async def test_create_ingest_key_respects_project_id(
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

    subject = f"filter-keys-{uuid.uuid4().hex[:8]}"
    await provision_user_principal(
        core_storage,
        subject=subject,
        email="filter-keys@example.com",
        name="Filter Keys",
    )
    token = _mint_jwt(private_key, sub=subject, email="filter-keys@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    other_subject = f"filter-keys-other-{uuid.uuid4().hex[:8]}"
    await provision_user_principal(
        core_storage,
        subject=other_subject,
        email="keys-other@example.com",
        name="Keys Other",
    )
    other_token = _mint_jwt(
        private_key,
        sub=other_subject,
        email="keys-other@example.com",
    )

    async with app.router.lifespan_context(app):
        async with client:
            _project_a, project_b = await _provision_user_with_two_projects(
                core_storage,
                client,
                headers,
            )
            create_b = await client.post(
                "/api/ingest-keys",
                json={"name": "project-b-key", "project_id": project_b},
                headers=headers,
            )
            list_b = await client.get(
                "/api/ingest-keys",
                params={"project_id": project_b},
                headers=headers,
            )
            denied = await client.post(
                "/api/ingest-keys",
                json={"name": "stolen-key", "project_id": project_b},
                headers={"Authorization": f"Bearer {other_token}"},
            )

    assert create_b.status_code == 201
    created = create_b.json()
    assert created["project_id"] == project_b
    assert "token" in created

    assert list_b.status_code == 200
    assert list_b.json()["total"] == 1
    assert list_b.json()["items"][0]["id"] == created["id"]

    assert denied.status_code == 404

    stored = await core_storage.get_ingest_key(created["id"])
    assert stored is not None
    assert stored.project_id == project_b
