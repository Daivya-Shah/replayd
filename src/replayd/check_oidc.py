"""Verify control-plane OIDC connectivity (issuer discovery + JWKS)."""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import httpx

from replayd.auth.oidc import oidc_configured, resolve_jwks_url
from replayd.config import Settings, get_settings


class OidcConnectivityError(Exception):
    """Raised when OIDC discovery or JWKS fetch fails."""


async def verify_oidc_connectivity(
    settings: Settings | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Fetch OpenID discovery and JWKS; return a result payload or raise."""
    resolved = settings or get_settings()
    if not oidc_configured(resolved):
        return {
            "configured": False,
            "status": "skipped",
            "detail": "OIDC_ISSUER is not set",
        }

    issuer = resolved.OIDC_ISSUER.rstrip("/")
    discovery_url = f"{issuer}/.well-known/openid-configuration"
    jwks_url = resolve_jwks_url(resolved)
    if jwks_url is None:
        raise OidcConnectivityError("OIDC JWKS URL could not be resolved")

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=10.0)

    try:
        discovery_resp = await client.get(discovery_url)
        discovery_resp.raise_for_status()
        discovery = discovery_resp.json()

        jwks_resp = await client.get(jwks_url)
        jwks_resp.raise_for_status()
        jwks = jwks_resp.json()
        keys = jwks.get("keys", [])
        if not isinstance(keys, list) or not keys:
            raise OidcConnectivityError(f"JWKS at {jwks_url} contains no keys")

        return {
            "configured": True,
            "status": "ok",
            "issuer": discovery.get("issuer", issuer),
            "discovery_url": discovery_url,
            "jwks_url": jwks_url,
            "jwks_key_count": len(keys),
            "audience": resolved.OIDC_AUDIENCE,
        }
    except httpx.HTTPError as exc:
        raise OidcConnectivityError(str(exc)) from exc
    finally:
        if owns_client and client is not None:
            await client.aclose()


def format_oidc_check_result(result: dict[str, Any]) -> str:
    if not result.get("configured"):
        return str(result.get("detail", "OIDC is not configured"))

    lines = [
        f"OK: OpenID discovery at {result['discovery_url']}",
        f"  issuer: {result.get('issuer')}",
        f"OK: JWKS at {result['jwks_url']} ({result['jwks_key_count']} keys)",
        f"  audience: {result.get('audience')}",
        "OIDC connectivity check passed.",
    ]
    return "\n".join(lines)


async def run_oidc_check(settings: Settings | None = None) -> int:
    resolved = settings or get_settings()
    if not oidc_configured(resolved):
        print("OIDC is not configured (OIDC_ISSUER is unset).")
        return 0

    try:
        result = await verify_oidc_connectivity(resolved)
        print(format_oidc_check_result(result))
        return 0
    except OidcConnectivityError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def main() -> None:
    raise SystemExit(asyncio.run(run_oidc_check()))


if __name__ == "__main__":
    main()
