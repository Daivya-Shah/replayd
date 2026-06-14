"""Control-plane authentication (OIDC JWT + shared API token)."""

from replayd.auth.oidc import OidcAuthError, OidcVerifier, oidc_configured
from replayd.auth.principal import (
    AuthenticationError,
    Principal,
    get_principal,
    resolve_principal,
)
from replayd.auth.tenancy import (
    ensure_user_tenant,
    resolve_accessible_project_ids,
)
from replayd.auth.scoping import resolve_read_scope

__all__ = [
    "AuthenticationError",
    "OidcAuthError",
    "OidcVerifier",
    "Principal",
    "ensure_user_tenant",
    "get_principal",
    "oidc_configured",
    "resolve_accessible_project_ids",
    "resolve_read_scope",
    "resolve_principal",
]
