"""Content-addressed blob store on the local filesystem."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from replayd.storage.blob_store import BlobStore


def blob_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def blob_object_key(digest: str) -> str:
    return f"blobs/{digest[:2]}/{digest}"


class FilesystemBlobStore(BlobStore):
    def __init__(self, storage_dir: str) -> None:
        self._storage_dir = Path(storage_dir)
        self._blob_dir = self._storage_dir / "blobs"

    async def init(self) -> None:
        await asyncio.to_thread(self._init_sync)

    def _init_sync(self) -> None:
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._blob_dir.mkdir(parents=True, exist_ok=True)

    async def aclose(self) -> None:
        return None

    def _blob_path(self, digest: str) -> Path:
        return self._blob_dir / digest[:2] / digest

    async def put_blob(self, data: bytes) -> str:
        digest = blob_digest(data)
        blob_path = self._blob_path(digest)
        if not blob_path.exists():
            await asyncio.to_thread(self._write_blob_file, blob_path, data)
        return digest

    @staticmethod
    def _write_blob_file(blob_path: Path, data: bytes) -> None:
        blob_path.parent.mkdir(parents=True, exist_ok=True)
        blob_path.write_bytes(data)

    async def get_blob(self, digest: str) -> bytes:
        blob_path = self._blob_path(digest)
        if not blob_path.is_file():
            raise FileNotFoundError(digest)
        return await asyncio.to_thread(blob_path.read_bytes)
