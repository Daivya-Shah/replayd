"""Branch replay-then-live demo against a parent run through the replayd proxy."""

from __future__ import annotations

import os
import sys
import uuid

from dotenv import load_dotenv

load_dotenv()

from openai import APIError, APIStatusError, OpenAI

from agent_steps import branch_chat_steps

PROXY_BASE_URL = "http://127.0.0.1:8787/v1"
RUN_ID_HEADER = "x-replayd-run-id"
BRANCH_HEADER = "x-replayd-branch"

# Step 1 uses a changed prompt (diverges); steps 2-3 match the parent recording.
BRANCH_STEP_ORIGINS = ("live", "replayed", "replayed")


def main() -> None:
    parent_run_id = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("REPLAYD_PARENT_RUN_ID")
    if not parent_run_id:
        print(
            "Error: provide a parent run id as a CLI argument or REPLAYD_PARENT_RUN_ID env var.",
            file=sys.stderr,
        )
        sys.exit(1)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    # Branch mode needs a real OpenAI key because diverged steps call the live model.
    branch_run_id = uuid.uuid4().hex
    client = OpenAI(
        api_key=api_key,
        base_url=PROXY_BASE_URL,
        default_headers={
            BRANCH_HEADER: parent_run_id,
            RUN_ID_HEADER: branch_run_id,
        },
    )

    request_headers = {
        BRANCH_HEADER: parent_run_id,
        RUN_ID_HEADER: branch_run_id,
    }

    print(f"Parent run id: {parent_run_id}")
    print(f"Branch run id: {branch_run_id}")

    try:
        for step_index, (step, origin) in enumerate(
            zip(branch_chat_steps(), BRANCH_STEP_ORIGINS, strict=True),
            start=1,
        ):
            response = client.chat.completions.create(
                **step,
                extra_headers=request_headers,
            )
            reply = response.choices[0].message.content or ""
            print(f"Step {step_index} ({origin}): {reply.strip()}")
    except APIStatusError as exc:
        print(f"HTTP status: {exc.status_code}", file=sys.stderr)
        print(f"Error: {exc.message}", file=sys.stderr)
        sys.exit(1)
    except APIError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
