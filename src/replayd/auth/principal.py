"""Principal resolution and JIT user provisioning for the control plane."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

import jwt
from fastapi import HTTPException, Request
from pydantic import BaseModel
from jwt import PyJWTError

from replayd.auth.oidc import (
    OidcAuthError,
    OidcVerifier,
    oidc_configured,
    resolve_oidc_algorithms,
)
from replayd.auth.tokens import (
    api_token_configured,
    extract_api_token,
    extract_bearer_token,
    tokens_match,
)
from replayd.auth.user_profile import (
    normalized_token_email,
    resolved_new_user_email,
    sync_user_profile_from_token,
)
from replayd.config import Settings
from replayd.models import User
from replayd.auth.tenancy import ensure_user_tenant
from replayd.storage.base import Storage

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when auth is required but credentials are missing or invalid."""


class Principal(BaseModel):
    kind: Literal["user", "service", "anonymous"]
    user_id: str | None = None
    email_verified: bool | None = None


def auth_configured(settings: Settings) -> bool:
    return oidc_configured(settings) or api_token_configured(settings)


def _unverified_bearer_diagnostics(bearer: str) -> dict[str, object]:
    diagnostics: dict[str, object] = {}
    try:
        header = jwt.get_unverified_header(bearer)
        diagnostics["alg"] = header.get("alg")
        diagnostics["kid"] = header.get("kid")
        claims = jwt.decode(
            bearer,
            options={
                "verify_signature": False,
                "verify_aud": False,
                "verify_exp": False,
            },
        )
        diagnostics["iss"] = claims.get("iss")
        diagnostics["aud"] = claims.get("aud")
        diagnostics["exp"] = claims.get("exp")
        if "client_id" in claims:
            diagnostics["client_id"] = claims.get("client_id")
        if "azp" in claims:
            diagnostics["azp"] = claims.get("azp")
    except PyJWTError as exc:
        diagnostics["decode_error"] = f"{type(exc).__name__}: {exc}"
    return diagnostics


def _expected_oidc_config(settings: Settings) -> dict[str, object]:
    return {
        "OIDC_ISSUER": settings.OIDC_ISSUER,
        "OIDC_AUDIENCE": settings.OIDC_AUDIENCE,
        "OIDC_ALGORITHMS": resolve_oidc_algorithms(settings),
    }


def _verification_error_detail(error: BaseException) -> str:
    cause = error.__cause__
    if cause is not None:
        return f"{type(cause).__name__}: {cause}"
    return f"{type(error).__name__}: {error}"


def _log_auth_rejection_warning(
    *,
    bearer_present: bool,
    bearer: str | None,
    settings: Settings,
    verification_error: BaseException | None = None,
) -> None:
    parts: list[str] = [f"bearer_present={bearer_present}"]
    if bearer_present and bearer:
        parts.append(f"token={_unverified_bearer_diagnostics(bearer)}")
    parts.append(f"expected={_expected_oidc_config(settings)}")
    if verification_error is not None:
        parts.append(f"verification_error={_verification_error_detail(verification_error)}")
    logger.warning("control plane auth rejected: %s", " ".join(parts))


async def provision_user_principal(
    storage: Storage,
    *,
    subject: str,
    email: str | None,
    name: str | None,
    email_verified: bool = False,
) -> Principal:
    existing = await storage.get_user_by_subject(subject)
    if existing is not None:
        user = await sync_user_profile_from_token(
            storage,
            existing,
            email=email,
            name=name,
            email_verified=email_verified,
        )
        await ensure_user_tenant(storage, user)
        return Principal(
            kind="user",
            user_id=user.id,
            email_verified=email_verified if normalized_token_email(email) else False,
        )

    trimmed_name = name.strip() if name and name.strip() else None
    user = User(
        id=uuid.uuid4().hex,
        email=resolved_new_user_email(subject, email),
        subject=subject,
        name=trimmed_name,
        created_at=datetime.now(UTC),
    )
    await storage.create_user(user)
    await ensure_user_tenant(storage, user)
    return Principal(
        kind="user",
        user_id=user.id,
        email_verified=email_verified if normalized_token_email(email) else False,
    )


async def resolve_principal(
    request: Request,
    storage: Storage,
    settings: Settings,
    verifier: OidcVerifier,
) -> Principal:
    if not auth_configured(settings):
        return Principal(kind="anonymous", user_id=None)

    bearer = extract_bearer_token(request)
    oidc_verification_error: BaseException | None = None
    if bearer and oidc_configured(settings):
        try:
            claims = verifier.verify(bearer)
            return await provision_user_principal(
                storage,
                subject=claims.sub,
                email=claims.email,
                name=claims.name,
                email_verified=claims.email_verified,
            )
        except OidcAuthError as exc:
            oidc_verification_error = exc

    if api_token_configured(settings):
        expected = settings.REPLAYD_API_TOKEN
        provided = extract_api_token(request)
        if (
            expected is not None
            and provided is not None
            and tokens_match(expected, provided)
        ):
            return Principal(kind="service", user_id=None)

    _log_auth_rejection_warning(
        bearer_present=bearer is not None,
        bearer=bearer,
        settings=settings,
        verification_error=oidc_verification_error,
    )
    raise AuthenticationError()


def get_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return principal
