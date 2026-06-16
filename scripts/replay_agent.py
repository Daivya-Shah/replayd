"""Replay a recorded run through the Replayd proxy in sandbox mode."""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

load_dotenv()

from openai import APIError, APIStatusError, OpenAI

from agent_steps import (
    REPLAYD_REPLAY_RUN_ID_ENV,
    REPLAY_HEADER,
    proxy_default_headers,
    resolve_proxy_base_url,
    run_demo_chat_steps,
)


def main() -> None:
    replay_run_id = os.environ.get(REPLAYD_REPLAY_RUN_ID_ENV)
    if not replay_run_id and len(sys.argv) > 1:
        replay_run_id = sys.argv[1]
    if not replay_run_id:
        print(
            "Error: provide a run id as a CLI argument or set REPLAYD_REPLAY_RUN_ID.",
            file=sys.stderr,
        )
        sys.exit(1)

    api_key = os.environ.get("OPENAI_API_KEY", "replay-dummy-key")
    header_overrides = (
        {} if os.environ.get(REPLAYD_REPLAY_RUN_ID_ENV) else {REPLAY_HEADER: replay_run_id}
    )
    client = OpenAI(
        api_key=api_key,
        base_url=resolve_proxy_base_url(),
        default_headers=proxy_default_headers(**header_overrides),
    )

    print(f"Replaying run: {replay_run_id}")

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
