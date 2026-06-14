"""Per-user tenant provisioning and project access resolution."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from replayd.models import Membership, Organization, Project, User
from replayd.storage.base import Storage

if TYPE_CHECKING:
    from replayd.auth.principal import Principal

DEFAULT_USER_PROJECT_NAME = "Default Project"
DEFAULT_USER_PROJECT_SLUG = "default"
OWNER_ROLE = "owner"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "org"


def derive_organization_name(
    *,
    email: str,
    name: str | None,
    subject: str,
) -> str:
    if name and name.strip():
        return name.strip()
    if "@" in email:
        local_part = email.split("@", 1)[0].strip()
        if local_part:
            return local_part.replace(".", " ").replace("_", " ").title()
    return f"User {subject[:8]}"


def derive_organization_slug(*, user_id: str) -> str:
    return f"user-{_slugify(user_id[:12])}"


async def ensure_user_tenant(storage: Storage, user: User) -> None:
    """Ensure the user has at least one org, default project, and owner membership."""
    memberships = await storage.list_memberships_for_user(user.id)
    if memberships:
        return

    now = datetime.now(UTC)
    org_id = uuid.uuid4().hex
    project_id = uuid.uuid4().hex
    membership_id = uuid.uuid4().hex
    subject = user.subject or user.id

    organization = Organization(
        id=org_id,
        name=derive_organization_name(
            email=user.email,
            name=user.name,
            subject=subject,
        ),
        slug=derive_organization_slug(user_id=user.id),
        created_at=now,
    )
    project = Project(
        id=project_id,
        org_id=org_id,
        name=DEFAULT_USER_PROJECT_NAME,
        slug=DEFAULT_USER_PROJECT_SLUG,
        created_at=now,
    )
    membership = Membership(
        id=membership_id,
        org_id=org_id,
        user_id=user.id,
        role=OWNER_ROLE,
        created_at=now,
    )

    await storage.create_organization(organization)
    await storage.create_project(project)
    await storage.create_membership(membership)


async def resolve_accessible_project_ids(
    storage: Storage,
    principal: Principal,
) -> list[str]:
    """Return project IDs the principal may access via org memberships."""
    if principal.kind != "user" or principal.user_id is None:
        return []
    return await storage.list_accessible_project_ids(principal.user_id)
