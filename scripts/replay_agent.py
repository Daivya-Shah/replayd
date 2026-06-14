"""Replay a recorded run through the replayd proxy in sandbox mode."""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

load_dotenv()

from openai import APIError, APIStatusError, OpenAI

from agent_steps import run_demo_chat_steps

PROXY_BASE_URL = "http://127.0.0.1:8787/v1"
REPLAY_HEADER = "x-replayd-replay"


def main() -> None:
    run_id = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("REPLAYD_RUN_ID")
    if not run_id:
        print(
            "Error: provide a run id as a CLI argument or REPLAYD_RUN_ID env var.",
            file=sys.stderr,
        )
        sys.exit(1)

    # A dummy API key is fine: replay mode matches request bodies against storage
    # and returns recorded responses without calling the upstream provider.
    api_key = os.environ.get("OPENAI_API_KEY", "replay-dummy-key")
    client = OpenAI(
        api_key=api_key,
        base_url=PROXY_BASE_URL,
        default_headers={REPLAY_HEADER: run_id},
    )

    print(f"Replaying run: {run_id}")

    try:
        replay_headers = {REPLAY_HEADER: run_id}
        replies = run_demo_chat_steps(client, extra_headers=replay_headers)
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
