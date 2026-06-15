"""Invitee-facing invitation accept and decline helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException

from replayd.auth.principal import Principal
from replayd.auth.tenancy import normalize_invitation_email
from replayd.auth.user_profile import login_email_for_invites
from replayd.models import IncomingInvitation, Invitation
from replayd.storage.base import Storage


def incoming_invitation_to_json(invitation: IncomingInvitation) -> dict[str, object]:
    return {
        "id": invitation.id,
        "organization_id": invitation.organization_id,
        "organization_name": invitation.organization_name,
        "role": invitation.role,
        "invited_by": invitation.invited_by,
        "created_at": invitation.created_at,
    }


async def _verified_invitee_email(
    storage: Storage,
    principal: Principal,
    *,
    token_email: str | None = None,
) -> str:
    if principal.kind != "user" or principal.user_id is None:
        raise HTTPException(status_code=403, detail="forbidden")
    if not principal.email_verified:
        raise HTTPException(status_code=403, detail="forbidden")

    user = await storage.get_user(principal.user_id)
    if user is None:
        raise HTTPException(status_code=403, detail="forbidden")

    email = login_email_for_invites(token_email=token_email, user_email=user.email)
    if email is None:
        raise HTTPException(status_code=403, detail="forbidden")
    return normalize_invitation_email(email)


async def list_incoming_invitations_for_principal(
    storage: Storage,
    principal: Principal,
) -> list[IncomingInvitation]:
    if principal.kind != "user" or principal.user_id is None or not principal.email_verified:
        return []

    user = await storage.get_user(principal.user_id)
    if user is None:
        return []

    email = login_email_for_invites(token_email=None, user_email=user.email)
    if email is None:
        return []

    return await storage.list_incoming_invitations_for_email(
        normalize_invitation_email(email),
    )


async def _load_pending_invitation_for_invitee(
    storage: Storage,
    principal: Principal,
    invitation_id: str,
) -> Invitation:
    invitation = await storage.get_invitation(invitation_id)
    if invitation is None or invitation.status != "pending":
        raise HTTPException(status_code=404, detail="invitation not found")

    now = datetime.now(UTC)
    if invitation.expires_at <= now:
        raise HTTPException(status_code=404, detail="invitation not found")

    user = await storage.get_user(principal.user_id)  # type: ignore[arg-type]
    if user is None:
        raise HTTPException(status_code=403, detail="forbidden")

    invitee_email = await _verified_invitee_email(storage, principal)
    if normalize_invitation_email(invitation.email) != invitee_email:
        raise HTTPException(status_code=403, detail="forbidden")

    return invitation


async def accept_invitation_for_invitee(
    storage: Storage,
    principal: Principal,
    invitation_id: str,
) -> None:
    assert principal.user_id is not None

    invitation = await storage.get_invitation(invitation_id)
    if invitation is None:
        raise HTTPException(status_code=404, detail="invitation not found")

    if invitation.status == "accepted":
        membership = await storage.get_membership_for_org_user(
            invitation.org_id,
            principal.user_id,
        )
        if membership is not None:
            invitee_email = await _verified_invitee_email(storage, principal)
            if normalize_invitation_email(invitation.email) == invitee_email:
                return
        raise HTTPException(status_code=404, detail="invitation not found")

    invitation = await _load_pending_invitation_for_invitee(
        storage,
        principal,
        invitation_id,
    )
    await storage.accept_invitation(invitation, principal.user_id)


async def decline_invitation_for_invitee(
    storage: Storage,
    principal: Principal,
    invitation_id: str,
) -> None:
    invitation = await _load_pending_invitation_for_invitee(
        storage,
        principal,
        invitation_id,
    )
    declined = await storage.decline_invitation(invitation.id)
    if not declined:
        raise HTTPException(status_code=404, detail="invitation not found")
