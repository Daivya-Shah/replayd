"""Abstract content-addressed blob store."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BlobStore(ABC):
    @abstractmethod
    async def init(self) -> None:
        """Prepare the blob backend (directories, bucket, etc.)."""

    @abstractmethod
    async def aclose(self) -> None:
        """Release backend resources."""

    @abstractmethod
    async def put_blob(self, data: bytes) -> str:
        """Store bytes and return the sha256 hex digest. Identical blobs dedupe."""

    @abstractmethod
    async def get_blob(self, digest: str) -> bytes:
        """Load bytes by content digest.

        Raises FileNotFoundError when the digest is unknown.
        """
