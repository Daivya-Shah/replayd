"""One-shot database migration entrypoint."""

from __future__ import annotations

from replayd.config import get_settings
from replayd.migrations.runner import upgrade_head_sync
from replayd.storage.factory import resolve_database_url


def main() -> None:
    settings = get_settings()
    upgrade_head_sync(resolve_database_url(settings))


if __name__ == "__main__":
    main()
