"""Storage factory and database URL resolution."""

from __future__ import annotations

from pathlib import Path

from replayd.config import Settings
from replayd.storage.base import Storage
from replayd.storage.blob_store import BlobStore
from replayd.storage.blobs import FilesystemBlobStore
from replayd.storage.s3_blobs import S3BlobStore
from replayd.storage.sql import SqlStorage


def resolve_database_url(settings: Settings) -> str:
    if settings.DATABASE_URL:
        return settings.DATABASE_URL
    db_path = Path(settings.STORAGE_DIR) / "replayd.db"
    return f"sqlite+aiosqlite:///{db_path.resolve().as_posix()}"


def get_blob_store(settings: Settings) -> BlobStore:
    if settings.BLOB_STORAGE_BACKEND == "s3":
        return S3BlobStore(
            bucket=settings.BLOB_S3_BUCKET,
            region=settings.BLOB_S3_REGION,
            endpoint_url=settings.BLOB_S3_ENDPOINT_URL,
            access_key_id=settings.BLOB_S3_ACCESS_KEY_ID,
            secret_access_key=settings.BLOB_S3_SECRET_ACCESS_KEY,
        )
    return FilesystemBlobStore(settings.STORAGE_DIR)


def get_storage(settings: Settings) -> Storage:
    return SqlStorage(
        database_url=resolve_database_url(settings),
        storage_dir=settings.STORAGE_DIR,
        run_migrations_on_startup=settings.RUN_MIGRATIONS_ON_STARTUP,
        blob_store=get_blob_store(settings),
    )
