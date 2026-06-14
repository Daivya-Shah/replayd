"""Backward-compatible alias for SqlStorage with storage_dir-only constructor."""

from __future__ import annotations

from pathlib import Path

from replayd.storage.sql import SqlStorage


class SqliteStorage(SqlStorage):
    def __init__(self, storage_dir: str) -> None:
        db_path = Path(storage_dir) / "replayd.db"
        super().__init__(
            database_url=f"sqlite+aiosqlite:///{db_path.resolve().as_posix()}",
            storage_dir=storage_dir,
        )


__all__ = ["SqliteStorage"]
