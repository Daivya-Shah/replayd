"""Read-scope tests for tenant-isolated control-plane endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from replayd.auth.principal import provision_user_principal
from replayd.auth.tenancy import resolve_accessible_project_ids
from replayd.config import Settings
from replayd.management import create_management_app
from replayd.models import RegressionTest
from replayd.storage.base import Storage
from test_oidc import (
    _generate_rsa_keypair,
    _management_client,
    _mint_jwt,
    _oidc_settings,
    _verifier_for_public_key,
)
from test_storage import _sample_exchange


def _now() -> datetime:
    return datetime(2026, 6, 13, 12, 0, 0, tzinfo=UTC)


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


async def _seed_run_exchange_and_test(
    storage: Storage,
    *,
    project_id: str,
    run_id: str,
    exchange_id: str,
    test_id: str,
) -> None:
    await storage.save_exchange(
        _sample_exchange(
            exchange_id=exchange_id,
            run_id=run_id,
            project_id=project_id,
        )
    )
    await storage.save_test(
        RegressionTest(
            id=test_id,
            name=f"Baseline {run_id[:8]}",
            baseline_run_id=run_id,
            project_id=project_id,
            created_at=_now(),
            mode="semantic",
        )
    )


def _unscoped_client(
    storage: Storage,
    tmp_path: Path,
) -> tuple[httpx.AsyncClient, object]:
    settings = Settings(STORAGE_DIR=str(tmp_path))
    app = create_management_app(settings=settings, storage=storage)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://mgmt"), app


@pytest.mark.asyncio
async def test_scoped_users_see_only_their_runs_and_tests(
    core_storage: Storage,
    rsa_keypair: tuple[object, object],
    tmp_path: Path,
) -> None:
    private_key, public_key = rsa_keypair
    settings = _oidc_settings(tmp_path)
    client, app = _management_client(core_storage, settings, _verifier_for_public_key(settings, public_key))

    subject_a = f"scope-user-a-{uuid.uuid4().hex[:8]}"
    subject_b = f"scope-user-b-{uuid.uuid4().hex[:8]}"
    _, project_a = await _provision_user(core_storage, subject=subject_a, email="a@example.com")
    _, project_b = await _provision_user(core_storage, subject=subject_b, email="b@example.com")

    run_a = f"run-a-{uuid.uuid4().hex}"
    run_b = f"run-b-{uuid.uuid4().hex}"
    exchange_a = f"exchange-a-{uuid.uuid4().hex}"
    exchange_b = f"exchange-b-{uuid.uuid4().hex}"
    test_a = f"test-a-{uuid.uuid4().hex}"
    test_b = f"test-b-{uuid.uuid4().hex}"

    await _seed_run_exchange_and_test(
        core_storage,
        project_id=project_a,
        run_id=run_a,
        exchange_id=exchange_a,
        test_id=test_a,
    )
    await _seed_run_exchange_and_test(
        core_storage,
        project_id=project_b,
        run_id=run_b,
        exchange_id=exchange_b,
        test_id=test_b,
    )

    token_a = _mint_jwt(private_key, sub=subject_a, email="a@example.com")
    token_b = _mint_jwt(private_key, sub=subject_b, email="b@example.com")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    async with app.router.lifespan_context(app):
        async with client:
            runs_a = await client.get("/api/runs", headers=headers_a)
            runs_b = await client.get("/api/runs", headers=headers_b)
            tests_a = await client.get("/api/tests", headers=headers_a)
            tests_b = await client.get("/api/tests", headers=headers_b)

    assert runs_a.status_code == 200
    assert runs_b.status_code == 200
    assert tests_a.status_code == 200
    assert tests_b.status_code == 200

    payload_runs_a = runs_a.json()
    payload_runs_b = runs_b.json()
    assert payload_runs_a["total"] == 1
    assert payload_runs_b["total"] == 1
    assert payload_runs_a["items"][0]["run_id"] == run_a
    assert payload_runs_b["items"][0]["run_id"] == run_b

    payload_tests_a = tests_a.json()
    payload_tests_b = tests_b.json()
    assert payload_tests_a["total"] == 1
    assert payload_tests_b["total"] == 1
    assert payload_tests_a["items"][0]["id"] == test_a
    assert payload_tests_b["items"][0]["id"] == test_b


@pytest.mark.asyncio
async def test_scoped_user_gets_404_for_other_users_details(
    core_storage: Storage,
    rsa_keypair: tuple[object, object],
    tmp_path: Path,
) -> None:
    private_key, public_key = rsa_keypair
    settings = _oidc_settings(tmp_path)
    client, app = _management_client(core_storage, settings, _verifier_for_public_key(settings, public_key))

    subject_a = f"scope-detail-a-{uuid.uuid4().hex[:8]}"
    subject_b = f"scope-detail-b-{uuid.uuid4().hex[:8]}"
    _, project_a = await _provision_user(core_storage, subject=subject_a, email="detail-a@example.com")
    _, project_b = await _provision_user(core_storage, subject=subject_b, email="detail-b@example.com")

    run_a = f"run-detail-a-{uuid.uuid4().hex}"
    run_b = f"run-detail-b-{uuid.uuid4().hex}"
    exchange_a = f"exchange-detail-a-{uuid.uuid4().hex}"
    exchange_b = f"exchange-detail-b-{uuid.uuid4().hex}"
    test_a = f"test-detail-a-{uuid.uuid4().hex}"
    test_b = f"test-detail-b-{uuid.uuid4().hex}"

    await _seed_run_exchange_and_test(
        core_storage,
        project_id=project_a,
        run_id=run_a,
        exchange_id=exchange_a,
        test_id=test_a,
    )
    await _seed_run_exchange_and_test(
        core_storage,
        project_id=project_b,
        run_id=run_b,
        exchange_id=exchange_b,
        test_id=test_b,
    )

    token_a = _mint_jwt(private_key, sub=subject_a, email="detail-a@example.com")
    headers_a = {"Authorization": f"Bearer {token_a}"}

    async with app.router.lifespan_context(app):
        async with client:
            own_run = await client.get(f"/api/runs/{run_a}", headers=headers_a)
            other_run = await client.get(f"/api/runs/{run_b}", headers=headers_a)
            own_exchange = await client.get(f"/api/exchanges/{exchange_a}", headers=headers_a)
            other_exchange = await client.get(f"/api/exchanges/{exchange_b}", headers=headers_a)
            own_test = await client.get(f"/api/tests/{test_a}", headers=headers_a)
            other_test = await client.get(f"/api/tests/{test_b}", headers=headers_a)

    assert own_run.status_code == 200
    assert own_exchange.status_code == 200
    assert own_test.status_code == 200
    assert other_run.status_code == 404
    assert other_exchange.status_code == 404
    assert other_test.status_code == 404


@pytest.mark.asyncio
async def test_unscoped_principal_sees_all_runs_and_tests(
    core_storage: Storage,
    tmp_path: Path,
) -> None:
    subject_a = f"scope-open-a-{uuid.uuid4().hex[:8]}"
    subject_b = f"scope-open-b-{uuid.uuid4().hex[:8]}"
    _, project_a = await _provision_user(core_storage, subject=subject_a, email="open-a@example.com")
    _, project_b = await _provision_user(core_storage, subject=subject_b, email="open-b@example.com")

    run_a = f"run-open-a-{uuid.uuid4().hex}"
    run_b = f"run-open-b-{uuid.uuid4().hex}"
    test_a = f"test-open-a-{uuid.uuid4().hex}"
    test_b = f"test-open-b-{uuid.uuid4().hex}"

    await _seed_run_exchange_and_test(
        core_storage,
        project_id=project_a,
        run_id=run_a,
        exchange_id=f"exchange-open-a-{uuid.uuid4().hex}",
        test_id=test_a,
    )
    await _seed_run_exchange_and_test(
        core_storage,
        project_id=project_b,
        run_id=run_b,
        exchange_id=f"exchange-open-b-{uuid.uuid4().hex}",
        test_id=test_b,
    )

    client, app = _unscoped_client(core_storage, tmp_path)

    async with app.router.lifespan_context(app):
        async with client:
            runs = await client.get("/api/runs")
            tests = await client.get("/api/tests")

    assert runs.status_code == 200
    assert tests.status_code == 200

    run_ids = {item["run_id"] for item in runs.json()["items"]}
    test_ids = {item["id"] for item in tests.json()["items"]}
    assert run_a in run_ids
    assert run_b in run_ids
    assert test_a in test_ids
    assert test_b in test_ids
    assert runs.json()["total"] >= 2
    assert tests.json()["total"] >= 2


@pytest.mark.asyncio
async def test_create_test_from_run_appears_in_user_test_list(
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

    subject = f"create-test-user-{uuid.uuid4().hex[:8]}"
    _, project_id = await _provision_user(
        core_storage,
        subject=subject,
        email="create-test@example.com",
    )
    run_id = f"run-create-test-{uuid.uuid4().hex}"
    await core_storage.save_exchange(
        _sample_exchange(
            exchange_id=f"exchange-create-test-{uuid.uuid4().hex}",
            run_id=run_id,
            project_id=project_id,
        )
    )

    token = _mint_jwt(private_key, sub=subject, email="create-test@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    async with app.router.lifespan_context(app):
        async with client:
            create_resp = await client.post(
                "/api/tests",
                json={
                    "name": "Saved baseline",
                    "baseline_run_id": run_id,
                    "mode": "semantic",
                },
                headers=headers,
            )
            list_resp = await client.get("/api/tests", headers=headers)

    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["baseline_run_id"] == run_id

    assert list_resp.status_code == 200
    payload = list_resp.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == created["id"]

    stored = await core_storage.get_test(created["id"])
    assert stored is not None
    assert stored.project_id == project_id
