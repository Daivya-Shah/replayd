"""CI-friendly CLI for running saved regression tests against the control plane."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import uuid
from collections.abc import Mapping
from typing import Any, TextIO

import httpx

DEFAULT_CONTROL_PLANE_URL = "http://localhost:8788"
DEFAULT_PROXY_URL = "http://localhost:8787/v1"
ENV_CONTROL_PLANE_URL = "REPLAYD_CONTROL_PLANE_URL"
ENV_PROXY_URL = "REPLAYD_PROXY_URL"
ENV_BASE_URL = "REPLAYD_BASE_URL"
ENV_API_TOKEN = "REPLAYD_API_TOKEN"
ENV_REPLAY_RUN_ID = "REPLAYD_REPLAY_RUN_ID"
ENV_RUN_ID = "REPLAYD_RUN_ID"
ENV_INGEST_KEY = "REPLAYD_INGEST_KEY"

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_ERROR = 2


def _normalize_base_url(url: str) -> str:
    return url.rstrip("/")


def normalize_proxy_url(url: str) -> str:
    normalized = _normalize_base_url(url)
    if not normalized.endswith("/v1"):
        return f"{normalized}/v1"
    return normalized


def resolve_control_plane_url(cli_value: str | None) -> str:
    if cli_value:
        return _normalize_base_url(cli_value)
    env_value = os.environ.get(ENV_CONTROL_PLANE_URL)
    if env_value:
        return _normalize_base_url(env_value)
    return DEFAULT_CONTROL_PLANE_URL


def resolve_proxy_url(cli_value: str | None) -> str:
    if cli_value:
        return normalize_proxy_url(cli_value)
    for env_name in (ENV_PROXY_URL, ENV_BASE_URL):
        env_value = os.environ.get(env_name)
        if env_value:
            return normalize_proxy_url(env_value)
    return DEFAULT_PROXY_URL


def resolve_api_token() -> str | None:
    token = os.environ.get(ENV_API_TOKEN)
    if token is None:
        return None
    stripped = token.strip()
    return stripped or None


def split_cli_and_agent_argv(argv: list[str]) -> tuple[list[str], list[str]]:
    if "--" in argv:
        index = argv.index("--")
        return argv[:index], argv[index + 1 :]
    return argv, []


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


def fetch_test(
    client: httpx.Client,
    test_id: str,
    *,
    err: TextIO | None = None,
) -> dict[str, Any] | None:
    stderr = err if err is not None else sys.stderr
    try:
        response = client.get(f"/api/tests/{test_id}")
    except httpx.RequestError as exc:
        print(f"ERROR: could not reach control plane: {exc}", file=stderr)
        return None

    if response.status_code == 401:
        print("ERROR: unauthorized (check REPLAYD_API_TOKEN)", file=stderr)
        return None

    if response.status_code == 404:
        print("ERROR: test not found", file=stderr)
        return None

    if not response.is_success:
        print(
            f"ERROR: control plane returned HTTP {response.status_code}",
            file=stderr,
        )
        return None

    try:
        return response.json()
    except ValueError:
        print("ERROR: control plane returned invalid JSON", file=stderr)
        return None


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


def build_replay_capture_env(
    *,
    proxy_base_url: str,
    baseline_run_id: str,
    candidate_run_id: str,
    parent_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = dict(parent_env or os.environ)
    env[ENV_BASE_URL] = proxy_base_url
    env[ENV_REPLAY_RUN_ID] = baseline_run_id
    env[ENV_RUN_ID] = candidate_run_id
    return env


def run_agent_command(
    command: list[str],
    env: Mapping[str, str],
    *,
    runner: Any = subprocess.run,
) -> int:
    if not command:
        return EXIT_ERROR
    completed = runner(command, env=env, check=False)
    return int(completed.returncode)


def run_with_agent(
    client: httpx.Client,
    test_id: str,
    agent_command: list[str],
    *,
    proxy_base_url: str,
    out: TextIO | None = None,
    err: TextIO | None = None,
    agent_runner: Any = subprocess.run,
    parent_env: Mapping[str, str] | None = None,
) -> int:
    stdout = out if out is not None else sys.stdout
    stderr = err if err is not None else sys.stderr

    test = fetch_test(client, test_id, err=stderr)
    if test is None:
        return EXIT_ERROR

    baseline_run_id = test.get("baseline_run_id")
    if not isinstance(baseline_run_id, str) or not baseline_run_id:
        print("ERROR: test response missing baseline_run_id", file=stderr)
        return EXIT_ERROR

    candidate_run_id = uuid.uuid4().hex
    print(f"Candidate run: {candidate_run_id}", file=stdout)

    agent_env = build_replay_capture_env(
        proxy_base_url=proxy_base_url,
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
        parent_env=parent_env,
    )
    agent_exit = run_agent_command(agent_command, agent_env, runner=agent_runner)

    compare_exit = run_regression_via_api(
        client,
        test_id,
        candidate_run_id,
        out=out,
        err=err,
    )
    if compare_exit == EXIT_ERROR:
        return EXIT_ERROR
    if agent_exit != 0 or compare_exit == EXIT_FAIL:
        return EXIT_FAIL
    return EXIT_PASS


def build_client(control_plane_url: str, api_token: str | None) -> httpx.Client:
    return httpx.Client(
        base_url=_normalize_base_url(control_plane_url),
        headers=_request_headers(api_token),
        timeout=30.0,
    )


def run_cli(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    cli_argv, agent_command = split_cli_and_agent_argv(argv)

    parser = argparse.ArgumentParser(
        prog="replayd-test",
        description="Run saved regression tests against the replayd control plane.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run",
        help="Compare a baseline test against a candidate run or drive an agent",
    )
    run_parser.add_argument("test_id", help="Regression test id")
    run_parser.add_argument(
        "--candidate",
        dest="candidate_run_id",
        default=None,
        help="Existing candidate run id (compare-only; omit when driving an agent)",
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
    run_parser.add_argument(
        "--proxy",
        dest="proxy_url",
        default=None,
        help=(
            f"Proxy base URL for agent replay-capture "
            f"(default: ${ENV_PROXY_URL} or {DEFAULT_PROXY_URL})"
        ),
    )

    try:
        args = parser.parse_args(cli_argv)
    except SystemExit as exc:
        if exc.code not in (0, None):
            return EXIT_ERROR
        return int(exc.code or 0)

    if args.command != "run":
        parser.print_help(file=sys.stderr)
        return EXIT_ERROR

    if args.candidate_run_id and agent_command:
        print(
            "ERROR: use either --candidate or an agent command after --, not both",
            file=sys.stderr,
        )
        return EXIT_ERROR

    if not args.candidate_run_id and not agent_command:
        print(
            "ERROR: provide --candidate or an agent command after --",
            file=sys.stderr,
        )
        return EXIT_ERROR

    control_plane_url = resolve_control_plane_url(args.control_plane_url)
    api_token = resolve_api_token()

    with build_client(control_plane_url, api_token) as client:
        if agent_command:
            return run_with_agent(
                client,
                args.test_id,
                agent_command,
                proxy_base_url=resolve_proxy_url(args.proxy_url),
            )

        assert args.candidate_run_id is not None
        return run_regression_via_api(
            client,
            args.test_id,
            args.candidate_run_id,
        )


def main(argv: list[str] | None = None) -> None:
    raise SystemExit(run_cli(argv))


if __name__ == "__main__":
    main()
