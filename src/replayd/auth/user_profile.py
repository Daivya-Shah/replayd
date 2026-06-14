"""Sync stored user profile fields from OIDC token claims."""

from __future__ import annotations

from replayd.models import User
from replayd.storage.base import Storage

PLACEHOLDER_EMAIL_SUFFIX = "@unknown.local"


def is_placeholder_email(email: str) -> bool:
    return email.endswith(PLACEHOLDER_EMAIL_SUFFIX)


def normalized_token_email(email: str | None) -> str | None:
    if email is None:
        return None
    stripped = email.strip()
    if not stripped:
        return None
    return stripped.lower()


def resolved_new_user_email(subject: str, email: str | None) -> str:
    token_email = normalized_token_email(email)
    if token_email:
        return token_email
    return f"{subject}{PLACEHOLDER_EMAIL_SUFFIX}"


def profile_updates_from_token(
    user: User,
    *,
    email: str | None,
    name: str | None,
    email_verified: bool,
) -> tuple[str | None, str | None]:
    """Return (email, name) updates, or None per field when unchanged."""
    email_update: str | None = None
    name_update: str | None = None

    token_email = normalized_token_email(email)
    if token_email:
        if is_placeholder_email(user.email) and user.email != token_email:
            email_update = token_email
        elif email_verified and user.email != token_email:
            email_update = token_email

    if name is not None:
        trimmed = name.strip()
        if trimmed and user.name != trimmed:
            name_update = trimmed

    return email_update, name_update


async def sync_user_profile_from_token(
    storage: Storage,
    user: User,
    *,
    email: str | None,
    name: str | None,
    email_verified: bool,
) -> User:
    email_update, name_update = profile_updates_from_token(
        user,
        email=email,
        name=name,
        email_verified=email_verified,
    )
    if email_update is None and name_update is None:
        return user

    updated = await storage.update_user_profile(
        user.id,
        email=email_update,
        name=name_update,
    )
    return updated if updated is not None else user


def login_email_for_invites(
    *,
    token_email: str | None,
    user_email: str,
) -> str | None:
    normalized = normalized_token_email(token_email)
    if normalized:
        return normalized
    if is_placeholder_email(user_email):
        return None
    return user_email
