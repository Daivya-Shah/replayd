"""Print the most recent captured exchanges from local storage."""

from __future__ import annotations

import asyncio
import sys

from replayd.config import get_settings
from replayd.storage.sqlite import SqliteStorage


async def _main() -> None:
    settings = get_settings()
    storage = SqliteStorage(settings.STORAGE_DIR)
    await storage.init()
    try:
        exchanges = await storage.list_exchanges(limit=20)
        if not exchanges:
            print("No exchanges recorded yet.")
            return

        print(
            f"{'id':<34} {'created_at':<28} {'method':<6} {'path':<24} "
            f"{'model':<14} {'status':<6} {'latency_ms'}"
        )
        for exchange in exchanges:
            print(
                f"{exchange.id:<34} "
                f"{exchange.created_at.isoformat():<28} "
                f"{exchange.method:<6} "
                f"{exchange.path:<24} "
                f"{(exchange.model or '-'):<14} "
                f"{exchange.response_status:<6} "
                f"{exchange.latency_ms}"
            )
    finally:
        await storage.aclose()


def main() -> None:
    try:
        asyncio.run(_main())
    except FileNotFoundError:
        print(
            f"No storage found at {get_settings().STORAGE_DIR}. "
            "Run the proxy and make at least one proxied request first.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
