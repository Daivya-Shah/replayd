"""Project management helpers for the control-plane API."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException

from replayd.auth.permissions import CREATE_PROJECT, RENAME_PROJECT, require_permission
from replayd.auth.principal import Principal
from replayd.auth.scoping import project_id_in_read_scope, resolve_read_scope
from replayd.auth.tenancy import DEFAULT_USER_PROJECT_SLUG, slugify_name
from replayd.models import Project
from replayd.storage.base import Storage
from replayd.tenancy import DEFAULT_ORG_ID


def is_default_project(project: Project) -> bool:
    return project.slug == DEFAULT_USER_PROJECT_SLUG


def project_to_json(project: Project) -> dict[str, object]:
    return {
        "id": project.id,
        "name": project.name,
        "slug": project.slug,
        "organization_id": project.org_id,
        "created_at": project.created_at,
        "is_default": is_default_project(project),
    }


async def generate_unique_project_slug(
    storage: Storage,
    org_id: str,
    name: str,
    *,
    exclude_project_id: str | None = None,
) -> str:
    base = slugify_name(name)
    slug = base
    counter = 2
    while await storage.project_slug_taken(
        org_id,
        slug,
        exclude_project_id=exclude_project_id,
    ):
        slug = f"{base}-{counter}"
        counter += 1
    return slug


async def resolve_primary_org_id(storage: Storage, principal: Principal) -> str:
    if principal.kind == "user" and principal.user_id is not None:
        memberships = await storage.list_memberships_for_user(principal.user_id)
        if not memberships:
            raise HTTPException(status_code=404, detail="organization not found")
        primary = min(memberships, key=lambda membership: membership.created_at)
        return primary.org_id
    return DEFAULT_ORG_ID


async def list_projects_for_principal(
    storage: Storage,
    principal: Principal,
) -> list[Project]:
    if principal.kind == "user" and principal.user_id is not None:
        return await storage.list_accessible_projects(principal.user_id)
    if principal.kind == "anonymous":
        return await storage.list_projects(DEFAULT_ORG_ID)
    return await storage.list_all_projects()


async def get_project_for_principal(
    storage: Storage,
    principal: Principal,
    project_id: str,
) -> Project:
    project = await storage.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    if principal.kind == "anonymous":
        if project.org_id != DEFAULT_ORG_ID:
            raise HTTPException(status_code=404, detail="project not found")
        return project

    scope = await resolve_read_scope(storage, principal)
    if not project_id_in_read_scope(project.id, scope):
        raise HTTPException(status_code=404, detail="project not found")
    return project


async def create_project_for_principal(
    storage: Storage,
    principal: Principal,
    *,
    name: str,
) -> Project:
    org_id = await resolve_primary_org_id(storage, principal)
    await require_permission(storage, principal, org_id, CREATE_PROJECT)
    now = datetime.now(UTC)
    slug = await generate_unique_project_slug(storage, org_id, name)
    project = Project(
        id=uuid.uuid4().hex,
        org_id=org_id,
        name=name.strip(),
        slug=slug,
        created_at=now,
    )
    await storage.create_project(project)
    return project


async def rename_project_for_principal(
    storage: Storage,
    principal: Principal,
    project_id: str,
    *,
    name: str,
) -> Project:
    project = await get_project_for_principal(storage, principal, project_id)
    await require_permission(storage, principal, project.org_id, RENAME_PROJECT)
    slug = await generate_unique_project_slug(
        storage,
        project.org_id,
        name,
        exclude_project_id=project.id,
    )
    updated = await storage.rename_project(project.id, name=name.strip(), slug=slug)
    if updated is None:
        raise HTTPException(status_code=404, detail="project not found")
    return updated
