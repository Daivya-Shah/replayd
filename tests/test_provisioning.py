"""Per-user tenant provisioning and project access resolution tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from replayd.auth.principal import Principal, provision_user_principal
from replayd.auth.tenancy import resolve_accessible_project_ids
from replayd.models import User
from replayd.storage.base import Storage


def _now() -> datetime:
    return datetime(2026, 6, 13, 12, 0, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_new_user_gets_org_project_and_owner_membership(
    core_storage: Storage,
) -> None:
    subject = f"provision-new-{uuid.uuid4().hex[:8]}"

    principal = await provision_user_principal(
        core_storage,
        subject=subject,
        email="new-user@example.com",
        name="New User",
    )

    assert principal.kind == "user"
    assert principal.user_id is not None

    memberships = await core_storage.list_memberships_for_user(principal.user_id)
    assert len(memberships) == 1
    assert memberships[0].role == "owner"

    org = await core_storage.get_organization(memberships[0].org_id)
    assert org is not None
    assert org.name == "New User"

    projects = await core_storage.list_projects(org.id)
    assert len(projects) == 1
    assert projects[0].name == "Default Project"
    assert projects[0].slug == "default"

    project_ids = await resolve_accessible_project_ids(core_storage, principal)
    assert project_ids == [projects[0].id]


@pytest.mark.asyncio
async def test_tenant_provisioning_is_idempotent(core_storage: Storage) -> None:
    subject = f"provision-idempotent-{uuid.uuid4().hex[:8]}"

    first = await provision_user_principal(
        core_storage,
        subject=subject,
        email="idempotent@example.com",
        name="Idempotent User",
    )
    second = await provision_user_principal(
        core_storage,
        subject=subject,
        email="idempotent@example.com",
        name="Idempotent User",
    )

    assert first.user_id == second.user_id

    memberships = await core_storage.list_memberships_for_user(first.user_id)
    assert len(memberships) == 1

    org = await core_storage.get_organization(memberships[0].org_id)
    assert org is not None
    projects = await core_storage.list_projects(org.id)
    assert len(projects) == 1


@pytest.mark.asyncio
async def test_provisioning_backfills_user_without_membership(
    core_storage: Storage,
) -> None:
    user_id = uuid.uuid4().hex
    subject = f"legacy-user-{uuid.uuid4().hex[:8]}"
    await core_storage.create_user(
        User(
            id=user_id,
            email="legacy@example.com",
            subject=subject,
            name="Legacy User",
            created_at=_now(),
        )
    )

    assert await core_storage.list_memberships_for_user(user_id) == []

    principal = await provision_user_principal(
        core_storage,
        subject=subject,
        email="legacy@example.com",
        name="Legacy User",
    )

    assert principal.user_id == user_id
    memberships = await core_storage.list_memberships_for_user(user_id)
    assert len(memberships) == 1
    assert memberships[0].role == "owner"


@pytest.mark.asyncio
async def test_two_users_get_isolated_tenants(core_storage: Storage) -> None:
    first = await provision_user_principal(
        core_storage,
        subject=f"user-a-{uuid.uuid4().hex[:8]}",
        email="user-a@example.com",
        name="User A",
    )
    second = await provision_user_principal(
        core_storage,
        subject=f"user-b-{uuid.uuid4().hex[:8]}",
        email="user-b@example.com",
        name="User B",
    )

    first_projects = await resolve_accessible_project_ids(core_storage, first)
    second_projects = await resolve_accessible_project_ids(core_storage, second)

    assert len(first_projects) == 1
    assert len(second_projects) == 1
    assert first_projects[0] != second_projects[0]

    first_memberships = await core_storage.list_memberships_for_user(first.user_id)
    second_memberships = await core_storage.list_memberships_for_user(second.user_id)
    assert first_memberships[0].org_id != second_memberships[0].org_id


@pytest.mark.asyncio
async def test_resolve_accessible_project_ids_for_non_user_principals(
    core_storage: Storage,
) -> None:
    assert (
        await resolve_accessible_project_ids(
            core_storage,
            Principal(kind="anonymous", user_id=None),
        )
        == []
    )
    assert (
        await resolve_accessible_project_ids(
            core_storage,
            Principal(kind="service", user_id=None),
        )
        == []
    )
