"""Control-plane authentication middleware."""

from __future__ import annotations

import logging
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from replayd.auth.oidc import OidcVerifier, oidc_configured
from replayd.auth.principal import AuthenticationError, auth_configured, resolve_principal
from replayd.auth.tokens import api_token_configured, extract_api_token, tokens_match
from replayd.config import Settings

logger = logging.getLogger(__name__)

_UNAUTHORIZED_RESPONSE = JSONResponse({"error": "unauthorized"}, status_code=401)


def log_unprotected_api_warning() -> None:
    logger.warning(
        "Neither REPLAYD_API_TOKEN nor OIDC is configured; control plane API is "
        "unprotected. Set REPLAYD_API_TOKEN and/or OIDC_ISSUER to require "
        "authentication on /api/* routes."
    )


class ApiTokenMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        *,
        settings: Settings,
        verifier: OidcVerifier | None = None,
        token_configured: Callable[[Settings], bool] = api_token_configured,
        extract_token: Callable[[Request], str | None] = extract_api_token,
    ) -> None:
        super().__init__(app)
        self._settings = settings
        self._verifier = verifier or OidcVerifier(settings)
        self._token_configured = token_configured
        self._extract_token = extract_token

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method == "OPTIONS" or not request.url.path.startswith("/api/"):
            return await call_next(request)

        storage = request.app.state.storage
        try:
            principal = await resolve_principal(
                request,
                storage,
                self._settings,
                self._verifier,
            )
        except AuthenticationError:
            return _UNAUTHORIZED_RESPONSE

        request.state.principal = principal
        return await call_next(request)


__all__ = [
    "ApiTokenMiddleware",
    "api_token_configured",
    "extract_api_token",
    "log_unprotected_api_warning",
    "oidc_configured",
    "tokens_match",
]
