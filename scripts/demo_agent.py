"""Demo multi-step agent run through the replayd proxy with a shared run id."""

from __future__ import annotations

import os
import sys
import uuid

from dotenv import load_dotenv

load_dotenv()

from openai import APIError, APIStatusError, OpenAI

from agent_steps import run_demo_chat_steps

PROXY_BASE_URL = "http://127.0.0.1:8787/v1"
RUN_ID_HEADER = "x-replayd-run-id"


def main() -> None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    run_id = uuid.uuid4().hex
    client = OpenAI(
        api_key=api_key,
        base_url=PROXY_BASE_URL,
        default_headers={RUN_ID_HEADER: run_id},
    )

    print(f"Run id: {run_id}")

    try:
        replies = run_demo_chat_steps(client)
        for step, reply in enumerate(replies, start=1):
            print(f"Step {step}: {reply.strip()}")
    except APIStatusError as exc:
        print(f"HTTP status: {exc.status_code}", file=sys.stderr)
        print(f"Error: {exc.message}", file=sys.stderr)
        sys.exit(1)
    except APIError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
