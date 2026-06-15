"""Demo multi-step agent run through the replayd proxy with a shared run id."""

from __future__ import annotations

import os
import sys
import uuid

from dotenv import load_dotenv

load_dotenv()

from openai import APIError, APIStatusError, OpenAI

from agent_steps import (
    REPLAYD_REPLAY_RUN_ID_ENV,
    REPLAYD_RUN_ID_ENV,
    RUN_ID_HEADER,
    proxy_default_headers,
    resolve_proxy_base_url,
    run_demo_chat_steps,
)


def main() -> None:
    replay_baseline = os.environ.get(REPLAYD_REPLAY_RUN_ID_ENV)
    if replay_baseline:
        api_key = os.environ.get("OPENAI_API_KEY", "replay-dummy-key")
    else:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print("Error: OPENAI_API_KEY environment variable is not set.", file=sys.stderr)
            sys.exit(1)

    run_id = os.environ.get(REPLAYD_RUN_ID_ENV) or uuid.uuid4().hex
    header_overrides: dict[str, str] = {}
    if not os.environ.get(REPLAYD_RUN_ID_ENV):
        header_overrides[RUN_ID_HEADER] = run_id

    client = OpenAI(
        api_key=api_key,
        base_url=resolve_proxy_base_url(),
        default_headers=proxy_default_headers(**header_overrides),
    )

    if not os.environ.get(REPLAYD_RUN_ID_ENV):
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
