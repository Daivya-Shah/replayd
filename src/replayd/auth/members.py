"""Organization membership management for the control-plane API."""

from __future__ import annotations

from fastapi import HTTPException

from replayd.auth.invitations import resolve_org_id_for_principal
from replayd.auth.permissions import REMOVE_MEMBER, require_permission
from replayd.auth.principal import Principal
from replayd.storage.base import Storage


async def remove_member_for_principal(
    storage: Storage,
    principal: Principal,
    target_user_id: str,
) -> None:
    org_id = await resolve_org_id_for_principal(storage, principal)
    assert principal.user_id is not None

    actor_membership = await storage.get_membership_for_org_user(org_id, principal.user_id)
    if actor_membership is None:
        raise HTTPException(status_code=404, detail="organization not found")

    target_membership = await storage.get_membership_for_org_user(org_id, target_user_id)
    if target_membership is None:
        raise HTTPException(status_code=404, detail="member not found")

    is_self = target_user_id == principal.user_id
    if not is_self:
        await require_permission(storage, principal, org_id, REMOVE_MEMBER)
        if (
            target_membership.role == "owner"
            and actor_membership.role == "admin"
        ):
            raise HTTPException(status_code=403, detail="forbidden")

    if target_membership.role == "owner":
        owner_count = await storage.count_owners(org_id)
        if owner_count <= 1:
            raise HTTPException(
                status_code=409,
                detail="cannot remove the last owner",
            )

    removed = await storage.remove_membership(org_id, target_user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="member not found")
