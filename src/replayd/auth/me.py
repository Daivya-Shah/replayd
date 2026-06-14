"""Current-user profile for GET /api/me."""

from __future__ import annotations

from fastapi import HTTPException

from replayd.auth.principal import Principal
from replayd.storage.base import Storage


async def build_me_profile(storage: Storage, principal: Principal) -> dict[str, object]:
    if principal.kind == "anonymous":
        return {"kind": "anonymous"}

    if principal.kind == "service":
        return {"kind": "service"}

    if principal.user_id is None:
        raise HTTPException(status_code=401, detail="not authenticated")

    user = await storage.get_user(principal.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    memberships = await storage.list_memberships_for_user(user.id)
    primary_org_id = (
        min(memberships, key=lambda membership: membership.created_at).org_id
        if memberships
        else None
    )

    membership_payload: list[dict[str, object]] = []
    for membership in sorted(memberships, key=lambda item: item.created_at):
        organization = await storage.get_organization(membership.org_id)
        membership_payload.append(
            {
                "organization_id": membership.org_id,
                "organization_name": organization.name if organization else "",
                "role": membership.role,
                "is_primary": membership.org_id == primary_org_id,
            }
        )

    return {
        "kind": "user",
        "user_id": user.id,
        "email": user.email,
        "email_verified": bool(principal.email_verified),
        "name": user.name,
        "created_at": user.created_at,
        "memberships": membership_payload,
    }
