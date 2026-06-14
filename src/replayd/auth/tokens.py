"""Shared API token helpers for the control plane."""

from __future__ import annotations

import hmac

from starlette.requests import Request

from replayd.config import Settings


def api_token_configured(settings: Settings) -> bool:
    token = settings.REPLAYD_API_TOKEN
    return token is not None and token != ""


def extract_bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization")
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        return token or None
    return None


def extract_api_token(request: Request) -> str | None:
    bearer = extract_bearer_token(request)
    if bearer is not None:
        return bearer

    header_token = request.headers.get("x-replayd-token")
    if header_token:
        token = header_token.strip()
        return token or None

    return None


def tokens_match(expected: str, provided: str) -> bool:
    return hmac.compare_digest(expected, provided)
