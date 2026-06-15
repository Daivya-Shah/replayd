"""Organization role-based access control for mutating control-plane actions."""

from __future__ import annotations

from typing import Final

from fastapi import HTTPException

from replayd.auth.principal import Principal
from replayd.storage.base import Storage

INVITE: Final = "invite"
REVOKE_INVITATION: Final = "revoke_invitation"
REMOVE_MEMBER: Final = "remove_member"
CREATE_PROJECT: Final = "create_project"
RENAME_PROJECT: Final = "rename_project"
CREATE_KEY: Final = "create_key"
REVOKE_KEY: Final = "revoke_key"

ALL_ACTIONS: frozenset[str] = frozenset(
    {
        INVITE,
        REVOKE_INVITATION,
        REMOVE_MEMBER,
        CREATE_PROJECT,
        RENAME_PROJECT,
        CREATE_KEY,
        REVOKE_KEY,
    }
)

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "owner": ALL_ACTIONS,
    "admin": frozenset(
        {
            INVITE,
            REVOKE_INVITATION,
            REMOVE_MEMBER,
            CREATE_PROJECT,
            RENAME_PROJECT,
            CREATE_KEY,
            REVOKE_KEY,
        }
    ),
    "member": frozenset(
        {
            CREATE_PROJECT,
            RENAME_PROJECT,
            CREATE_KEY,
            REVOKE_KEY,
        }
    ),
    "viewer": frozenset(),
}


def role_can(role: str, action: str) -> bool:
    return action in ROLE_PERMISSIONS.get(role, frozenset())


async def require_permission(
    storage: Storage,
    principal: Principal,
    organization_id: str,
    action: str,
) -> None:
    if principal.kind in {"anonymous", "service"}:
        return

    if principal.kind != "user" or principal.user_id is None:
        raise HTTPException(status_code=403, detail="forbidden")

    membership = await storage.get_membership_for_org_user(
        organization_id,
        principal.user_id,
    )
    if membership is None or not role_can(membership.role, action):
        raise HTTPException(status_code=403, detail="forbidden")
