"""OIDC JWT verification for the control plane."""

from __future__ import annotations

from typing import Any

import jwt
from jwt import PyJWKClient, PyJWKSet, PyJWTError

from replayd.config import Settings


class OidcAuthError(Exception):
    """Raised when a bearer token fails OIDC JWT validation."""


def oidc_configured(settings: Settings) -> bool:
    issuer = settings.OIDC_ISSUER
    return issuer is not None and issuer != ""


def resolve_jwks_url(settings: Settings) -> str | None:
    if settings.OIDC_JWKS_URL:
        return settings.OIDC_JWKS_URL
    if not oidc_configured(settings):
        return None
    return f"{settings.OIDC_ISSUER.rstrip('/')}/.well-known/jwks.json"


def resolve_oidc_algorithms(settings: Settings) -> list[str]:
    return [
        part.strip()
        for part in settings.OIDC_ALGORITHMS.split(",")
        if part.strip()
    ]


class InjectedJwksClient:
    """Hermetic JWKS source for tests — no network calls."""

    def __init__(self, jwks: dict[str, Any]) -> None:
        self._key_set = PyJWKSet.from_dict(jwks)

    def get_signing_key_from_jwt(self, token: str) -> Any:
        headers = jwt.get_unverified_header(token)
        kid = headers.get("kid")
        if kid is not None:
            for key in self._key_set.keys:
                if key.key_id == kid:
                    return key
            raise OidcAuthError(f'Unable to find a signing key that matches "{kid}"')
        if len(self._key_set.keys) == 1:
            return self._key_set.keys[0]
        raise OidcAuthError("Missing kid header and JWKS contains multiple keys")


class OidcClaims(dict):
    """Validated JWT claims needed for principal resolution."""

    @property
    def sub(self) -> str:
        return self["sub"]

    @property
    def email(self) -> str | None:
        return self.get("email")

    @property
    def name(self) -> str | None:
        return self.get("name")


class OidcVerifier:
    """Validates OIDC bearer tokens (ES384/RS256) against issuer JWKS."""

    def __init__(
        self,
        settings: Settings,
        *,
        jwks_client: PyJWKClient | InjectedJwksClient | None = None,
        algorithms: list[str] | None = None,
    ) -> None:
        self._settings = settings
        self._algorithms = algorithms or resolve_oidc_algorithms(settings)
        if jwks_client is not None:
            self._jwks_client = jwks_client
        elif resolve_jwks_url(settings) is not None:
            self._jwks_client = PyJWKClient(resolve_jwks_url(settings))
        else:
            self._jwks_client = None

    def verify(self, token: str) -> OidcClaims:
        if not oidc_configured(self._settings):
            raise OidcAuthError("OIDC is not configured")
        if self._jwks_client is None:
            raise OidcAuthError("OIDC JWKS client is not configured")

        issuer = self._settings.OIDC_ISSUER
        audience = self._settings.OIDC_AUDIENCE
        if issuer is None:
            raise OidcAuthError("OIDC issuer is not configured")
        if audience is None:
            raise OidcAuthError("OIDC audience is not configured")

        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=self._algorithms,
                issuer=issuer,
                audience=audience,
                options={"require": ["exp", "sub"]},
            )
        except PyJWTError as exc:
            raise OidcAuthError(str(exc)) from exc

        return OidcClaims(
            sub=str(claims["sub"]),
            email=claims.get("email"),
            name=claims.get("name"),
        )
