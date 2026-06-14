"""Control-plane authentication (OIDC JWT + shared API token)."""

from replayd.auth.oidc import OidcAuthError, OidcVerifier, oidc_configured
from replayd.auth.principal import (
    AuthenticationError,
    Principal,
    get_principal,
    resolve_principal,
)

__all__ = [
    "AuthenticationError",
    "OidcAuthError",
    "OidcVerifier",
    "Principal",
    "get_principal",
    "oidc_configured",
    "resolve_principal",
]
