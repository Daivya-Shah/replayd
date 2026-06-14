"""Multi-tenant storage tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from replayd.models import Membership, Organization, Project, User
from replayd.storage.base import Storage
from replayd.tenancy import DEFAULT_ORG_ID, DEFAULT_PROJECT_ID
from test_storage import _sample_exchange

OTHER_PROJECT_ID = "00000000-0000-4000-8000-000000000099"
OTHER_ORG_ID = "00000000-0000-4000-8000-000000000098"


def _now() -> datetime:
    return datetime(2026, 6, 13, 12, 0, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_organization_project_user_membership_crud_round_trip(
    core_storage: Storage,
) -> None:
    org_id = str(uuid.uuid4())
    project_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    membership_id = str(uuid.uuid4())
    created_at = _now()

    await core_storage.create_organization(
        Organization(
            id=org_id,
            name="Acme Corp",
            slug=f"acme-{org_id[:8]}",
            created_at=created_at,
        )
    )
    await core_storage.create_project(
        Project(
            id=project_id,
            org_id=org_id,
            name="Primary",
            slug="primary",
            created_at=created_at,
        )
    )
    await core_storage.create_user(
        User(
            id=user_id,
            email=f"user-{user_id[:8]}@example.com",
            subject=None,
            name="Test User",
            created_at=created_at,
        )
    )
    await core_storage.create_membership(
        Membership(
            id=membership_id,
            org_id=org_id,
            user_id=user_id,
            role="owner",
            created_at=created_at,
        )
    )

    loaded_org = await core_storage.get_organization(org_id)
    assert loaded_org is not None
    assert loaded_org.name == "Acme Corp"

    orgs = await core_storage.list_organizations()
    assert any(item.id == org_id for item in orgs)

    loaded_project = await core_storage.get_project(project_id)
    assert loaded_project is not None
    assert loaded_project.org_id == org_id

    projects = await core_storage.list_projects(org_id)
    assert len(projects) == 1
    assert projects[0].id == project_id

    loaded_user = await core_storage.get_user(user_id)
    assert loaded_user is not None
    assert loaded_user.email.endswith("@example.com")

    by_email = await core_storage.get_user_by_email(loaded_user.email)
    assert by_email is not None
    assert by_email.id == user_id

    loaded_membership = await core_storage.get_membership(membership_id)
    assert loaded_membership is not None
    assert loaded_membership.role == "owner"

    memberships = await core_storage.list_memberships(org_id)
    assert len(memberships) == 1
    assert memberships[0].user_id == user_id


@pytest.mark.asyncio
async def test_ingest_key_create_resolve_and_revoke(core_storage: Storage) -> None:
    key_model, plaintext = await core_storage.create_ingest_key(
        DEFAULT_PROJECT_ID,
        "ci-agent",
    )

    assert plaintext.startswith("rpd_")
    assert key_model.key_prefix == plaintext[:12]
    assert key_model.key_hash

    listed = await core_storage.list_ingest_keys(DEFAULT_PROJECT_ID)
    assert len(listed) == 1
    assert listed[0].key_prefix == key_model.key_prefix
    assert listed[0].key_hash == ""

    resolved = await core_storage.resolve_ingest_key(plaintext)
    assert resolved is not None
    assert resolved.id == key_model.id
    assert resolved.key_hash == key_model.key_hash

    assert await core_storage.resolve_ingest_key("rpd_wrong-token") is None

    assert await core_storage.revoke_ingest_key(key_model.id) is True
    assert await core_storage.resolve_ingest_key(plaintext) is None


@pytest.mark.asyncio
async def test_exchange_defaults_to_default_project_and_scopes_reads(
    core_storage: Storage,
) -> None:
    await core_storage.create_organization(
        Organization(
            id=OTHER_ORG_ID,
            name="Other Org",
            slug=f"other-{OTHER_ORG_ID[:8]}",
            created_at=_now(),
        )
    )
    await core_storage.create_project(
        Project(
            id=OTHER_PROJECT_ID,
            org_id=OTHER_ORG_ID,
            name="Other Project",
            slug="other",
            created_at=_now(),
        )
    )

    default_exchange = _sample_exchange(
        exchange_id="default-exchange",
        run_id="default-exchange-run",
    )
    other_exchange = _sample_exchange(
        exchange_id="other-exchange",
        run_id="other-exchange-run",
        project_id=OTHER_PROJECT_ID,
    )
    await core_storage.save_exchange(default_exchange)
    await core_storage.save_exchange(other_exchange)

    loaded_default = await core_storage.get_exchange(default_exchange.id)
    assert loaded_default is not None
    assert loaded_default.project_id == DEFAULT_PROJECT_ID

    all_exchanges = await core_storage.list_exchanges()
    assert len(all_exchanges) == 2

    default_only = await core_storage.list_exchanges(project_id=DEFAULT_PROJECT_ID)
    assert len(default_only) == 1
    assert default_only[0].id == default_exchange.id

    other_only = await core_storage.list_exchanges(project_id=OTHER_PROJECT_ID)
    assert len(other_only) == 1
    assert other_only[0].id == other_exchange.id

    assert await core_storage.count_exchanges() == 2
    assert await core_storage.count_exchanges(project_id=DEFAULT_PROJECT_ID) == 1

    await core_storage.save_exchange(
        _sample_exchange(
            exchange_id="default-run-step",
            run_id="default-run",
            project_id=None,
        )
    )
    await core_storage.save_exchange(
        _sample_exchange(
            exchange_id="other-run-step",
            run_id="other-run",
            project_id=OTHER_PROJECT_ID,
        )
    )

    all_runs = await core_storage.list_runs()
    assert len(all_runs) == 4

    default_runs = await core_storage.list_runs(project_id=DEFAULT_PROJECT_ID)
    assert {run.run_id for run in default_runs} == {
        "default-exchange-run",
        "default-run",
    }

    other_runs = await core_storage.list_runs(project_id=OTHER_PROJECT_ID)
    assert {run.run_id for run in other_runs} == {"other-exchange-run", "other-run"}

    assert await core_storage.count_runs() == 4
    assert await core_storage.count_runs(project_id=OTHER_PROJECT_ID) == 2
