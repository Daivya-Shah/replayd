"""Live smoke test: send a real OpenAI request through the running replayd proxy."""

from __future__ import annotations

import os
import sys

from openai import APIError, APIStatusError, OpenAI

PROXY_BASE_URL = "http://127.0.0.1:8787/v1"


def main() -> None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=api_key, base_url=PROXY_BASE_URL)

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Reply with exactly: replayd works"}],
            max_tokens=20,
        )
    except APIStatusError as exc:
        print(f"HTTP status: {exc.status_code}")
        print(f"Error: {exc.message}")
        sys.exit(1)
    except APIError as exc:
        print(f"Error: {exc}")
        sys.exit(1)

    reply = response.choices[0].message.content
    print("HTTP status: 200")
    print(f"Reply: {reply}")


if __name__ == "__main__":
    main()
