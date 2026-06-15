"""CI-friendly CLI for running saved regression tests against the control plane."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, TextIO

import httpx

DEFAULT_CONTROL_PLANE_URL = "http://localhost:8788"
ENV_CONTROL_PLANE_URL = "REPLAYD_CONTROL_PLANE_URL"
ENV_API_TOKEN = "REPLAYD_API_TOKEN"

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_ERROR = 2


def _normalize_base_url(url: str) -> str:
    return url.rstrip("/")


def resolve_control_plane_url(cli_value: str | None) -> str:
    if cli_value:
        return _normalize_base_url(cli_value)
    env_value = os.environ.get(ENV_CONTROL_PLANE_URL)
    if env_value:
        return _normalize_base_url(env_value)
    return DEFAULT_CONTROL_PLANE_URL


def resolve_api_token() -> str | None:
    token = os.environ.get(ENV_API_TOKEN)
    if token is None:
        return None
    stripped = token.strip()
    return stripped or None


def _request_headers(api_token: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_token is not None:
        headers["Authorization"] = f"Bearer {api_token}"
    return headers


def format_test_result(result: dict[str, Any]) -> str:
    status = str(result.get("status", "unknown")).upper()
    matched_steps = result.get("matched_steps", "?")
    total_steps = result.get("total_steps", "?")
    detail = result.get("detail", "")
    first_divergent = result.get("first_divergent_step_index")
    step_diffs = result.get("step_diffs") or []

    lines = [f"{status}: {matched_steps}/{total_steps} steps matched"]
    if detail:
        lines.append(f"Detail: {detail}")
    if first_divergent is not None:
        lines.append(f"First divergent step: {first_divergent}")
    if status == "FAIL" and step_diffs:
        lines.append("Step diffs:")
        for diff in step_diffs:
            step_index = diff.get("step_index", "?")
            request_match = diff.get("request_match")
            response_match = diff.get("response_match")
            diff_kind = diff.get("diff_kind", "none")
            request_label = "match" if request_match else "DIFF"
            response_label = "match" if response_match else "DIFF"
            lines.append(
                f"  step {step_index}: request={request_label}, "
                f"response={response_label}, diff_kind={diff_kind}"
            )
    return "\n".join(lines)


def process_run_response(
    response: httpx.Response,
    *,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    stdout = out if out is not None else sys.stdout
    stderr = err if err is not None else sys.stderr

    if response.status_code == 401:
        print("ERROR: unauthorized (check REPLAYD_API_TOKEN)", file=stderr)
        return EXIT_ERROR

    if response.status_code == 404:
        print("ERROR: test not found", file=stderr)
        return EXIT_ERROR

    if not response.is_success:
        print(
            f"ERROR: control plane returned HTTP {response.status_code}",
            file=stderr,
        )
        return EXIT_ERROR

    try:
        result = response.json()
    except ValueError:
        print("ERROR: control plane returned invalid JSON", file=stderr)
        return EXIT_ERROR

    print(format_test_result(result), file=stdout)

    status = str(result.get("status", "")).lower()
    if status == "pass":
        return EXIT_PASS
    if status == "fail":
        return EXIT_FAIL

    print(f"ERROR: unexpected test status: {result.get('status')!r}", file=stderr)
    return EXIT_ERROR


def run_regression_via_api(
    client: httpx.Client,
    test_id: str,
    candidate_run_id: str,
    *,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    stderr = err if err is not None else sys.stderr

    try:
        response = client.post(
            f"/api/tests/{test_id}/run",
            json={"candidate_run_id": candidate_run_id},
        )
    except httpx.RequestError as exc:
        print(f"ERROR: could not reach control plane: {exc}", file=stderr)
        return EXIT_ERROR

    return process_run_response(response, out=out, err=err)


def build_client(control_plane_url: str, api_token: str | None) -> httpx.Client:
    return httpx.Client(
        base_url=_normalize_base_url(control_plane_url),
        headers=_request_headers(api_token),
        timeout=30.0,
    )


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="replayd-test",
        description="Run saved regression tests against the replayd control plane.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run",
        help="Compare a baseline test against a candidate run",
    )
    run_parser.add_argument("test_id", help="Regression test id")
    run_parser.add_argument(
        "--candidate",
        required=True,
        dest="candidate_run_id",
        help="Candidate run id to compare against the test baseline",
    )
    run_parser.add_argument(
        "--control-plane",
        dest="control_plane_url",
        default=None,
        help=(
            f"Control plane base URL "
            f"(default: ${ENV_CONTROL_PLANE_URL} or {DEFAULT_CONTROL_PLANE_URL})"
        ),
    )

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code not in (0, None):
            return EXIT_ERROR
        return int(exc.code or 0)

    if args.command != "run":
        parser.print_help(file=sys.stderr)
        return EXIT_ERROR

    control_plane_url = resolve_control_plane_url(args.control_plane_url)
    api_token = resolve_api_token()

    with build_client(control_plane_url, api_token) as client:
        return run_regression_via_api(
            client,
            args.test_id,
            args.candidate_run_id,
        )


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
