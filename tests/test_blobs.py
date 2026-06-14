"""BlobStore conformance tests across filesystem and optional S3 backends."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from replayd.storage.blob_store import BlobStore
from blob_backends import blob_store_params, close_blob_store, open_blob_store

SAMPLE_A = b'{"model":"gpt-4o","messages":[{"role":"user","content":"hello"}]}'
SAMPLE_B = b'{"model":"gpt-4o","messages":[{"role":"user","content":"world"}]}'


@pytest.fixture(params=blob_store_params())
async def blob_store(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> AsyncIterator[BlobStore]:
    backend: str = request.param
    store, bucket_name = await open_blob_store(backend, tmp_path)
    try:
        yield store
    finally:
        await close_blob_store(store, backend, bucket_name)


@pytest.mark.asyncio
async def test_put_get_round_trip(blob_store: BlobStore) -> None:
    digest = await blob_store.put_blob(SAMPLE_A)
    assert digest == hashlib.sha256(SAMPLE_A).hexdigest()
    assert await blob_store.get_blob(digest) == SAMPLE_A


@pytest.mark.asyncio
async def test_put_is_idempotent_for_identical_bytes(blob_store: BlobStore) -> None:
    first_digest = await blob_store.put_blob(SAMPLE_A)
    second_digest = await blob_store.put_blob(SAMPLE_A)

    assert first_digest == second_digest
    assert await blob_store.get_blob(first_digest) == SAMPLE_A


@pytest.mark.asyncio
async def test_distinct_bytes_produce_distinct_digests(blob_store: BlobStore) -> None:
    digest_a = await blob_store.put_blob(SAMPLE_A)
    digest_b = await blob_store.put_blob(SAMPLE_B)

    assert digest_a != digest_b
    assert await blob_store.get_blob(digest_a) == SAMPLE_A
    assert await blob_store.get_blob(digest_b) == SAMPLE_B


@pytest.mark.asyncio
async def test_get_unknown_digest_raises_file_not_found(blob_store: BlobStore) -> None:
    unknown_digest = hashlib.sha256(b"never-stored").hexdigest()

    with pytest.raises(FileNotFoundError):
        await blob_store.get_blob(unknown_digest)
