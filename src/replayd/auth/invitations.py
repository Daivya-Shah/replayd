"""Organization invitation helpers for the control-plane API."""

from __future__ import annotations

import re

from fastapi import HTTPException

from replayd.auth.principal import Principal
from replayd.auth.projects import resolve_primary_org_id
from replayd.models import Invitation, OrgMember
from replayd.storage.base import Storage

INVITATION_TTL_DAYS = 14
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


from replayd.auth.tenancy import normalize_invitation_email


def invitation_to_json(invitation: Invitation) -> dict[str, object]:
    return {
        "id": invitation.id,
        "organization_id": invitation.org_id,
        "email": invitation.email,
        "role": invitation.role,
        "status": invitation.status,
        "invited_by_user_id": invitation.invited_by_user_id,
        "created_at": invitation.created_at,
        "accepted_at": invitation.accepted_at,
        "expires_at": invitation.expires_at,
    }


def org_member_to_json(member: OrgMember) -> dict[str, object]:
    return {
        "user_id": member.user_id,
        "email": member.email,
        "role": member.role,
        "joined_at": member.joined_at,
    }


async def resolve_org_id_for_principal(
    storage: Storage,
    principal: Principal,
) -> str:
    if principal.kind != "user" or principal.user_id is None:
        raise HTTPException(status_code=404, detail="organization not found")
    return await resolve_primary_org_id(storage, principal)


async def get_invitation_for_principal(
    storage: Storage,
    principal: Principal,
    invitation_id: str,
) -> Invitation:
    org_id = await resolve_org_id_for_principal(storage, principal)
    invitation = await storage.get_invitation(invitation_id)
    if invitation is None or invitation.org_id != org_id:
        raise HTTPException(status_code=404, detail="invitation not found")
    return invitation


def _validate_invitation_email(email: str) -> str:
    normalized = normalize_invitation_email(email)
    if not _EMAIL_PATTERN.match(normalized):
        raise HTTPException(status_code=400, detail="email is invalid")
    return normalized


async def create_invitation_for_principal(
    storage: Storage,
    principal: Principal,
    *,
    email: str,
    role: str | None,
) -> Invitation:
    org_id = await resolve_org_id_for_principal(storage, principal)
    assert principal.user_id is not None
    normalized_email = _validate_invitation_email(email)
    invite_role = role or "member"
    if invite_role not in {"owner", "admin", "member", "viewer"}:
        raise HTTPException(status_code=400, detail="role is invalid")

    if await storage.has_pending_invitation_for_org_email(org_id, normalized_email):
        raise HTTPException(status_code=409, detail="invitation already pending")

    existing_user = await storage.get_user_by_email(normalized_email)
    if existing_user is not None:
        membership = await storage.get_membership_for_org_user(org_id, existing_user.id)
        if membership is not None:
            raise HTTPException(status_code=409, detail="user is already a member")

    return await storage.create_invitation(
        org_id=org_id,
        email=normalized_email,
        role=invite_role,
        invited_by_user_id=principal.user_id,
    )


async def list_invitations_for_principal(
    storage: Storage,
    principal: Principal,
) -> list[Invitation]:
    org_id = await resolve_org_id_for_principal(storage, principal)
    return await storage.list_invitations(org_id, status="pending")


async def revoke_invitation_for_principal(
    storage: Storage,
    principal: Principal,
    invitation_id: str,
) -> None:
    invitation = await get_invitation_for_principal(storage, principal, invitation_id)
    if invitation.status != "pending":
        raise HTTPException(status_code=404, detail="invitation not found")
    revoked = await storage.revoke_invitation(invitation.id)
    if not revoked:
        raise HTTPException(status_code=404, detail="invitation not found")


async def list_members_for_principal(
    storage: Storage,
    principal: Principal,
) -> list[OrgMember]:
    org_id = await resolve_org_id_for_principal(storage, principal)
    return await storage.list_memberships_for_org(org_id)
