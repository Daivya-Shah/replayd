"""Record a fresh run and compare it to a baseline for regression detection."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid

from dotenv import load_dotenv

load_dotenv()

from openai import APIError, APIStatusError, OpenAI

from agent_steps import run_demo_chat_steps
from replayd.config import get_settings
from replayd.semantics import compare_response_semantics, extract_semantics
from replayd.storage import get_storage
from replayd.testing import compare_runs

PROXY_BASE_URL = "http://127.0.0.1:8787/v1"
RUN_ID_HEADER = "x-replayd-run-id"


def _record_candidate_run(baseline_run_id: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    candidate_run_id = uuid.uuid4().hex
    client = OpenAI(
        api_key=api_key,
        base_url=PROXY_BASE_URL,
        default_headers={RUN_ID_HEADER: candidate_run_id},
    )

    print(f"Baseline run: {baseline_run_id}")
    print(f"Recording candidate run: {candidate_run_id}")

    try:
        replies = run_demo_chat_steps(client)
        for step, reply in enumerate(replies, start=1):
            print(f"Candidate step {step}: {reply.strip()}")
    except APIStatusError as exc:
        print(f"HTTP status: {exc.status_code}", file=sys.stderr)
        print(f"Error: {exc.message}", file=sys.stderr)
        sys.exit(1)
    except APIError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    return candidate_run_id


def _print_result(label: str, result: object) -> None:
    print(f"\n{label}")
    print(f"  Result: {result.status.upper()}")
    print(f"  Detail: {result.detail}")
    print(f"  Matched steps: {result.matched_steps}/{result.total_steps}")
    if result.step_diffs:
        for diff in result.step_diffs:
            request_status = "match" if diff.request_match else "DIFF"
            response_status = "match" if diff.response_match else "DIFF"
            print(
                f"  step {diff.step_index}: request={request_status}, "
                f"response={response_status}, diff_kind={diff.diff_kind}"
            )


def _print_synthetic_semantic_example() -> None:
    request_body = json.dumps(
        {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "book a table"}],
        }
    ).encode()
    baseline_response = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "book_restaurant",
                                    "arguments": '{"city":"Paris","party_size":2}',
                                },
                            }
                        ],
                    },
                }
            ]
        }
    ).encode()
    candidate_same_tool = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "book_restaurant",
                                    "arguments": '{"city":"Lyon","party_size":4}',
                                },
                            }
                        ],
                    },
                }
            ]
        }
    ).encode()
    candidate_different_tool = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "cancel_reservation",
                                    "arguments": '{"reservation_id":"abc"}',
                                },
                            }
                        ],
                    },
                }
            ]
        }
    ).encode()

    baseline = extract_semantics(request_body, baseline_response, {})
    same_tool = extract_semantics(request_body, candidate_same_tool, {})
    different_tool = extract_semantics(request_body, candidate_different_tool, {})

    same_match, same_kind = compare_response_semantics(
        baseline.response,
        same_tool.response,
        baseline_contents=baseline.response_contents,
        candidate_contents=same_tool.response_contents,
    )
    tool_match, tool_kind = compare_response_semantics(
        baseline.response,
        different_tool.response,
        baseline_contents=baseline.response_contents,
        candidate_contents=different_tool.response_contents,
    )

    print("\nSynthetic semantic examples (offline, no API):")
    print(
        "  Same tool name + argument keys, different argument values -> "
        f"semantic {'PASS' if same_match else 'FAIL'} (diff_kind={same_kind})"
    )
    print(
        "  Different tool/function name (book_restaurant vs cancel_reservation) -> "
        f"semantic {'PASS' if tool_match else 'FAIL'} (diff_kind={tool_kind})"
    )
    print(
        "  A live candidate that switches tool_choice would flip semantic mode to FAIL "
        "even when exact mode only sees a byte-level response diff."
    )


async def _compare_and_print(baseline_run_id: str, candidate_run_id: str) -> None:
    settings = get_settings()
    storage = get_storage(settings)
    await storage.init()
    try:
        exact_result = await compare_runs(
            storage,
            baseline_run_id,
            candidate_run_id,
            mode="exact",
        )
        semantic_result = await compare_runs(
            storage,
            baseline_run_id,
            candidate_run_id,
            mode="semantic",
        )
    finally:
        await storage.aclose()

    print()
    print("Comparison modes (baseline vs fresh candidate run):")
    _print_result("Exact hash mode", exact_result)
    _print_result("Semantic mode", semantic_result)
    print(
        "\nNote: LLM wording is usually nondeterministic, so exact mode often FAILs while "
        "semantic mode PASSes when the model made the same structural decisions."
    )
    _print_synthetic_semantic_example()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Record a fresh agent run and compare it to a baseline.",
    )
    parser.add_argument(
        "baseline_run_id",
        help="Run id of the recorded baseline to compare against",
    )
    args = parser.parse_args()

    candidate_run_id = _record_candidate_run(args.baseline_run_id)
    asyncio.run(_compare_and_print(args.baseline_run_id, candidate_run_id))


if __name__ == "__main__":
    main()
