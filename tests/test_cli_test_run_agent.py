"""End-to-end replayd-test run with agent replay-capture."""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import uvicorn

from replayd.cli.test_cmd import EXIT_FAIL, EXIT_PASS, run_cli
from replayd.config import Settings
from replayd.main import create_app
from replayd.management import create_management_app
from replayd.models import Exchange, RegressionTest
from db_backends import close_test_storage, open_test_storage

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
BASELINE_RUN_ID = "e2e-agent-baseline"
API_TOKEN = "e2e-agent-token"
RESPONSE_BODIES = [
    b'{"id":"resp-1","choices":[{"message":{"content":"reply 1"}}]}',
    b'{"id":"resp-2","choices":[{"message":{"content":"reply 2"}}]}',
    b'{"id":"resp-3","choices":[{"message":{"content":"reply 3"}}]}',
]


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _demo_request_bodies() -> list[bytes]:
    sys.path.insert(0, str(SCRIPTS_DIR))
    from agent_steps import demo_chat_request_bodies

    return demo_chat_request_bodies()


class _UvicornThread:
    def __init__(self, app: object, port: int) -> None:
        self._port = port
        self._server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                log_level="error",
                ws="none",
            ),
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self) -> None:
        self._thread.start()
        self._wait_until_ready()

    def _wait_until_ready(self) -> None:
        url = f"http://127.0.0.1:{self._port}/health"
        for _ in range(100):
            try:
                response = httpx.get(url, timeout=0.2)
                if response.status_code == 200:
                    return
            except httpx.RequestError:
                pass
            time.sleep(0.05)
        raise RuntimeError(f"server on port {self._port} failed to start")


@pytest.fixture
async def agent_e2e_stack(tmp_path: Path) -> Iterator[dict[str, object]]:
    storage, schema = await open_test_storage("sqlite", tmp_path)
    request_bodies = _demo_request_bodies()
    started_at = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)

    for index, (request_body, response_body) in enumerate(
        zip(request_bodies, RESPONSE_BODIES, strict=True),
    ):
        step_started = started_at + timedelta(seconds=index)
        request_hash = await storage.put_blob(request_body)
        response_hash = await storage.put_blob(response_body)
        await storage.save_exchange(
            Exchange(
                id=uuid.uuid4().hex,
                run_id=BASELINE_RUN_ID,
                parent_run_id=None,
                origin="live",
                created_at=step_started,
                started_at=step_started,
                ended_at=step_started + timedelta(milliseconds=10),
                latency_ms=10,
                method="POST",
                path="/v1/chat/completions",
                query=None,
                request_headers={"content-type": "application/json"},
                request_body_hash=request_hash,
                response_status=200,
                response_headers={"content-type": "application/json"},
                model="gpt-4o-mini",
                usage=None,
                provider=None,
                response_body_hash=response_hash,
            )
        )

    test_id = uuid.uuid4().hex
    await storage.save_test(
        RegressionTest(
            id=test_id,
            name="e2e agent replay capture",
            baseline_run_id=BASELINE_RUN_ID,
            created_at=datetime.now(UTC),
            mode="exact",
        )
    )

    storage_dir = str(tmp_path)
    proxy_port = _find_free_port()
    mgmt_port = _find_free_port()

    proxy_app = create_app(
        settings=Settings(
            STORAGE_DIR=storage_dir,
            CAPTURE_ENABLED=True,
        ),
    )
    mgmt_app = create_management_app(
        settings=Settings(
            STORAGE_DIR=storage_dir,
            MGMT_CORS_ORIGIN="http://localhost:3000",
            REPLAYD_API_TOKEN=API_TOKEN,
        ),
    )

    proxy_server = _UvicornThread(proxy_app, proxy_port)
    mgmt_server = _UvicornThread(mgmt_app, mgmt_port)
    proxy_server.start()
    mgmt_server.start()

    agent_script = SCRIPTS_DIR / "replay_capture_demo_agent.py"
    demo_agent_script = SCRIPTS_DIR / "demo_agent.py"
    diverging_script = SCRIPTS_DIR / "diverging_demo_agent.py"

    try:
        yield {
            "test_id": test_id,
            "proxy_url": f"http://127.0.0.1:{proxy_port}/v1",
            "control_plane_url": f"http://127.0.0.1:{mgmt_port}",
            "agent_command": [sys.executable, str(agent_script)],
            "demo_agent_command": [sys.executable, str(demo_agent_script)],
            "diverging_agent_command": [sys.executable, str(diverging_script)],
            "scripts_dir": str(SCRIPTS_DIR),
            "storage": storage,
            "schema": schema,
        }
    finally:
        await close_test_storage(storage, "sqlite", schema)


def _run_cli_with_stack(
    stack: dict[str, object],
    agent_command: list[str],
) -> int:
    previous_environ = os.environ.copy()
    try:
        os.environ["REPLAYD_API_TOKEN"] = API_TOKEN
        scripts_path = str(stack["scripts_dir"])
        existing_pythonpath = os.environ.get("PYTHONPATH", "")
        os.environ["PYTHONPATH"] = (
            scripts_path
            if not existing_pythonpath
            else scripts_path + os.pathsep + existing_pythonpath
        )
        return run_cli(
            [
                "run",
                str(stack["test_id"]),
                "--control-plane",
                str(stack["control_plane_url"]),
                "--proxy",
                str(stack["proxy_url"]),
                "--",
                *agent_command,
            ],
        )
    finally:
        os.environ.clear()
        os.environ.update(previous_environ)


def test_cli_run_with_agent_replay_capture_exits_zero(
    agent_e2e_stack: dict[str, object],
) -> None:
    exit_code = _run_cli_with_stack(
        agent_e2e_stack,
        agent_e2e_stack["agent_command"],  # type: ignore[arg-type]
    )
    assert exit_code == EXIT_PASS


def test_cli_run_with_demo_agent_replay_capture_exits_zero(
    agent_e2e_stack: dict[str, object],
) -> None:
    exit_code = _run_cli_with_stack(
        agent_e2e_stack,
        agent_e2e_stack["demo_agent_command"],  # type: ignore[arg-type]
    )
    assert exit_code == EXIT_PASS


def test_cli_run_with_diverging_agent_exits_one(
    agent_e2e_stack: dict[str, object],
) -> None:
    exit_code = _run_cli_with_stack(
        agent_e2e_stack,
        agent_e2e_stack["diverging_agent_command"],  # type: ignore[arg-type]
    )
    assert exit_code == EXIT_FAIL
