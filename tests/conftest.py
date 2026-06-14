"""Shared pytest fixtures for dual-database core tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from replayd.storage.base import Storage
from db_backends import close_test_storage, dual_params, open_test_storage


@pytest.fixture(params=dual_params())
async def core_storage(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Storage]:
    backend: str = request.param
    storage, database_name = await open_test_storage(backend, tmp_path)
    try:
        yield storage
    finally:
        await close_test_storage(storage, backend, database_name)
