"""Demo agent that diverges on step 1 for replay-capture regression tests."""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

load_dotenv()

from openai import APIError, APIStatusError, OpenAI

from agent_steps import (
    DEMO_MAX_TOKENS,
    DEMO_MODEL,
    proxy_default_headers,
    resolve_proxy_base_url,
)


def main() -> None:
    api_key = os.environ.get("OPENAI_API_KEY", "replay-dummy-key")
    client = OpenAI(
        api_key=api_key,
        base_url=resolve_proxy_base_url(),
        default_headers=proxy_default_headers(),
    )

    diverging_step = {
        "model": DEMO_MODEL,
        "messages": [
            {
                "role": "user",
                "content": "This prompt was never recorded in the baseline run.",
            }
        ],
        "max_tokens": DEMO_MAX_TOKENS,
    }

    try:
        client.chat.completions.create(**diverging_step)
    except APIStatusError as exc:
        print(f"HTTP status: {exc.status_code}", file=sys.stderr)
        print(f"Error: {exc.message}", file=sys.stderr)
        sys.exit(1)
    except APIError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
