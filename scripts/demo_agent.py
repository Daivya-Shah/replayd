"""Demo multi-step agent run through the Replayd proxy with a shared run id."""

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
    REPLAY_HEADER,
    RUN_ID_HEADER,
    proxy_default_headers,
    resolve_proxy_base_url,
    run_demo_chat_steps,
)


def _proxy_headers() -> dict[str, str]:
    """Build per-request proxy headers for record, replay, or replay-capture."""
    headers = proxy_default_headers()
    replay_baseline = os.environ.get(REPLAYD_REPLAY_RUN_ID_ENV)

    if replay_baseline:
        candidate_run_id = os.environ.get(REPLAYD_RUN_ID_ENV)
        if not candidate_run_id:
            print(
                "Error: REPLAYD_RUN_ID is required when REPLAYD_REPLAY_RUN_ID is set "
                "(replay-capture mode).",
                file=sys.stderr,
            )
            sys.exit(1)
        headers[REPLAY_HEADER] = replay_baseline
        headers[RUN_ID_HEADER] = candidate_run_id
        return headers

    if RUN_ID_HEADER not in headers:
        run_id = uuid.uuid4().hex
        headers[RUN_ID_HEADER] = run_id
        print(f"Run id: {run_id}")

    return headers


def main() -> None:
    replay_baseline = os.environ.get(REPLAYD_REPLAY_RUN_ID_ENV)
    if replay_baseline:
        api_key = os.environ.get("OPENAI_API_KEY", "replay-dummy-key")
    else:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print("Error: OPENAI_API_KEY environment variable is not set.", file=sys.stderr)
            sys.exit(1)

    headers = _proxy_headers()
    client = OpenAI(
        api_key=api_key,
        base_url=resolve_proxy_base_url(),
        default_headers=headers,
    )

    try:
        replies = run_demo_chat_steps(client, extra_headers=headers)
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
