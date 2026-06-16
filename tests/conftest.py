"""Shared pytest fixtures for dual-database core tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from replayd.storage.base import Storage
from db_backends import close_test_storage, dual_params, open_test_storage

# Env vars that enable control-plane auth when set via shell or pydantic's `.env` load.
_AUTH_ENV_VARS = (
    "REPLAYD_API_TOKEN",
    "OIDC_ISSUER",
    "OIDC_JWKS_URL",
    "OIDC_AUDIENCE",
)


@pytest.fixture(autouse=True)
def isolate_control_plane_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests hermetic: no ambient service token or OIDC from shell/.env."""
    for name in _AUTH_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
        # Empty string overrides `.env` (delenv alone still lets pydantic-settings read .env).
        monkeypatch.setenv(name, "")


@pytest.fixture(params=dual_params())
async def core_storage(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Storage]:
    backend: str = request.param
    storage, database_name = await open_test_storage(backend, tmp_path)
    try:
        yield storage
    finally:
        await close_test_storage(storage, backend, database_name)
