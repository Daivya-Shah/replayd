"""Read-scope resolution for control-plane list and detail endpoints."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from replayd.storage.base import Storage
from replayd.tenancy import DEFAULT_PROJECT_ID

if TYPE_CHECKING:
    from replayd.auth.principal import Principal

from replayd.models import Exchange, ProjectIngestKey, RegressionTest

# None = unscoped (all projects). [] = scoped user with no projects. [...] = filter.
ReadScope = list[str] | None


async def resolve_read_scope(storage: Storage, principal: Principal) -> ReadScope:
    """Return project IDs to filter reads, or None when reads stay unscoped."""
    if principal.kind == "user" and principal.user_id is not None:
        return await storage.list_accessible_project_ids(principal.user_id)
    return None


def resolved_project_id(project_id: str | None) -> str:
    return project_id or DEFAULT_PROJECT_ID


def project_id_in_read_scope(project_id: str | None, scope: ReadScope) -> bool:
    if scope is None:
        return True
    if not scope:
        return False
    return resolved_project_id(project_id) in scope


def exchange_in_read_scope(exchange: Exchange, scope: ReadScope) -> bool:
    return project_id_in_read_scope(exchange.project_id, scope)


def regression_test_in_read_scope(test: RegressionTest, scope: ReadScope) -> bool:
    return project_id_in_read_scope(test.project_id, scope)


def run_steps_in_read_scope(steps: Sequence[Exchange], scope: ReadScope) -> bool:
    if scope is None:
        return bool(steps)
    if not steps or not scope:
        return False
    return all(project_id_in_read_scope(step.project_id, scope) for step in steps)


async def resolve_ingest_key_list_project_ids(
    storage: Storage,
    principal: Principal,
) -> Sequence[str] | None:
    """Project IDs to list ingest keys for, or None when unscoped (all projects)."""
    scope = await resolve_read_scope(storage, principal)
    if scope is not None:
        return scope
    if principal.kind == "anonymous":
        return [DEFAULT_PROJECT_ID]
    return None


async def resolve_list_project_ids_filter(
    storage: Storage,
    principal: Principal,
    project_id: str | None,
    default_project_ids: Sequence[str] | None,
) -> Sequence[str] | None:
    """Apply an optional project_id query filter on top of the default list scope."""
    if project_id is None:
        return default_project_ids
    from replayd.auth.projects import get_project_for_principal

    await get_project_for_principal(storage, principal, project_id)
    return [project_id]
