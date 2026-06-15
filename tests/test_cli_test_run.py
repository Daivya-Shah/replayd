"""Tests for the replayd-test CLI."""

import io
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from replayd.cli.test_cmd import (
    EXIT_ERROR,
    EXIT_FAIL,
    EXIT_PASS,
    process_run_response,
    run_cli,
)
from replayd.config import Settings
from replayd.management import create_management_app
from replayd.models import Exchange, RegressionTest
from replayd.storage.base import Storage
from db_backends import close_test_storage, dual_params, open_test_storage

BASELINE_RUN_ID = "cli-baseline-run"
PASSING_CANDIDATE_RUN_ID = "cli-passing-candidate"
FAILING_CANDIDATE_RUN_ID = "cli-failing-candidate"
REQUEST_BODIES = [
    b'{"model":"gpt-4o-mini","messages":[{"role":"user","content":"step 1"}]}',
    b'{"model":"gpt-4o-mini","messages":[{"role":"user","content":"step 2"}]}',
    b'{"model":"gpt-4o-mini","messages":[{"role":"user","content":"step 3"}]}',
]
RESPONSE_BODIES = [
    b'{"id":"r1","choices":[{"message":{"content":"reply 1"}}]}',
    b'{"id":"r2","choices":[{"message":{"content":"reply 2"}}]}',
    b'{"id":"r3","choices":[{"message":{"content":"reply 3"}}]}',
]
API_TOKEN = "cli-test-token"


@pytest.fixture
def management_settings() -> Settings:
    return Settings(
        STORAGE_DIR="./data",
        MGMT_CORS_ORIGIN="http://localhost:3000",
        REPLAYD_API_TOKEN=API_TOKEN,
    )


async def _copy_run(
    storage: Storage,
    source_run_id: str,
    dest_run_id: str,
    *,
    step_overrides: dict[int, dict[str, object]] | None = None,
) -> None:
    steps = await storage.get_run(source_run_id)
    for index, step in enumerate(steps, start=1):
        overrides = (step_overrides or {}).get(index, {})
        copied = step.model_copy(
            update={"id": uuid.uuid4().hex, "run_id": dest_run_id, **overrides},
        )
        await storage.save_exchange(copied)


@pytest.fixture(params=dual_params())
async def regression_cli_fixture(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> AsyncIterator[tuple[Storage, str, str, str]]:
    backend: str = request.param
    storage, schema = await open_test_storage(backend, tmp_path)

    started_at = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)
    for index, (request_body, response_body) in enumerate(
        zip(REQUEST_BODIES, RESPONSE_BODIES, strict=True),
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

    await _copy_run(storage, BASELINE_RUN_ID, PASSING_CANDIDATE_RUN_ID)

    wrong_response_hash = await storage.put_blob(b'{"id":"different"}')
    await _copy_run(
        storage,
        BASELINE_RUN_ID,
        FAILING_CANDIDATE_RUN_ID,
        step_overrides={2: {"response_body_hash": wrong_response_hash}},
    )

    test_id = uuid.uuid4().hex
    await storage.save_test(
        RegressionTest(
            id=test_id,
            name="cli regression test",
            baseline_run_id=BASELINE_RUN_ID,
            created_at=datetime.now(UTC),
            mode="exact",
        )
    )

    try:
        yield storage, test_id, PASSING_CANDIDATE_RUN_ID, FAILING_CANDIDATE_RUN_ID
    finally:
        await close_test_storage(storage, backend, schema)


@asynccontextmanager
async def _management_client(
    storage: Storage,
    settings: Settings,
    *,
    api_token: str | None = API_TOKEN,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_management_app(settings=settings, storage=storage)
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_token is not None:
        headers["Authorization"] = f"Bearer {api_token}"
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://mgmt",
            headers=headers,
        ) as client:
            yield client


async def _post_run(
    client: httpx.AsyncClient,
    test_id: str,
    candidate_run_id: str,
    *,
    out: io.StringIO | None = None,
    err: io.StringIO | None = None,
) -> int:
    response = await client.post(
        f"/api/tests/{test_id}/run",
        json={"candidate_run_id": candidate_run_id},
    )
    return process_run_response(response, out=out, err=err)


@pytest.mark.asyncio
async def test_cli_run_passing_candidate_exits_zero(
    regression_cli_fixture: tuple[Storage, str, str, str],
    management_settings: Settings,
) -> None:
    storage, test_id, passing_candidate, _ = regression_cli_fixture
    out = io.StringIO()

    async with _management_client(storage, management_settings) as client:
        exit_code = await _post_run(
            client,
            test_id,
            passing_candidate,
            out=out,
        )

    assert exit_code == EXIT_PASS
    output = out.getvalue()
    assert "PASS" in output
    assert "3/3 steps matched" in output


@pytest.mark.asyncio
async def test_cli_run_diverging_candidate_exits_one(
    regression_cli_fixture: tuple[Storage, str, str, str],
    management_settings: Settings,
) -> None:
    storage, test_id, _, failing_candidate = regression_cli_fixture
    out = io.StringIO()

    async with _management_client(storage, management_settings) as client:
        exit_code = await _post_run(
            client,
            test_id,
            failing_candidate,
            out=out,
        )

    assert exit_code == EXIT_FAIL
    output = out.getvalue()
    assert "FAIL" in output
    assert "First divergent step: 2" in output
    assert "step 2:" in output


@pytest.mark.asyncio
async def test_cli_run_missing_test_exits_two(
    regression_cli_fixture: tuple[Storage, str, str, str],
    management_settings: Settings,
) -> None:
    storage, _, passing_candidate, _ = regression_cli_fixture
    err = io.StringIO()

    async with _management_client(storage, management_settings) as client:
        exit_code = await _post_run(
            client,
            "missing-test-id",
            passing_candidate,
            err=err,
        )

    assert exit_code == EXIT_ERROR
    assert "test not found" in err.getvalue().lower()


@pytest.mark.asyncio
async def test_cli_run_missing_auth_exits_two(
    regression_cli_fixture: tuple[Storage, str, str, str],
    management_settings: Settings,
) -> None:
    storage, test_id, passing_candidate, _ = regression_cli_fixture
    err = io.StringIO()

    async with _management_client(
        storage,
        management_settings,
        api_token=None,
    ) as client:
        exit_code = await _post_run(
            client,
            test_id,
            passing_candidate,
            err=err,
        )

    assert exit_code == EXIT_ERROR
    assert "unauthorized" in err.getvalue().lower()


def test_cli_usage_error_exits_two() -> None:
    assert run_cli(["run", "test-id"]) == EXIT_ERROR
