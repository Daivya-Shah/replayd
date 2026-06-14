import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from replayd.config import Settings
from replayd.management import create_management_app
from replayd.models import Exchange, RegressionTest
from replayd.storage.base import Storage
from replayd.testing import compare_runs, run_regression_test
from db_backends import close_test_storage, dual_params, open_test_storage

BASELINE_RUN_ID = "baseline-run"
CANDIDATE_RUN_ID = "candidate-run"
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


@pytest.fixture
def management_settings() -> Settings:
    return Settings(
        STORAGE_DIR="./data",
        MGMT_CORS_ORIGIN="http://localhost:3000",
    )


@pytest.fixture(params=dual_params())
async def baseline_storage(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> AsyncIterator[Storage]:
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

    try:
        yield storage
    finally:
        await close_test_storage(storage, backend, schema)


@pytest.fixture(params=dual_params())
async def divergent_baseline_storage(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> AsyncIterator[Storage]:
    backend: str = request.param
    storage, schema = await open_test_storage(backend, tmp_path)

    started_at = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)
    shared_request_hash = await storage.put_blob(REQUEST_BODIES[0])
    response_one = await storage.put_blob(RESPONSE_BODIES[0])
    response_two = await storage.put_blob(RESPONSE_BODIES[1])

    await storage.save_exchange(
        Exchange(
            id=uuid.uuid4().hex,
            run_id=BASELINE_RUN_ID,
            parent_run_id=None,
            origin="live",
            created_at=started_at,
            started_at=started_at,
            ended_at=started_at + timedelta(milliseconds=10),
            latency_ms=10,
            method="POST",
            path="/v1/chat/completions",
            query=None,
            request_headers={"content-type": "application/json"},
            request_body_hash=shared_request_hash,
            response_status=200,
            response_headers={"content-type": "application/json"},
            model="gpt-4o-mini",
            usage=None,
            provider=None,
            response_body_hash=response_one,
        )
    )
    second_started = started_at + timedelta(seconds=1)
    await storage.save_exchange(
        Exchange(
            id=uuid.uuid4().hex,
            run_id=BASELINE_RUN_ID,
            parent_run_id=None,
            origin="live",
            created_at=second_started,
            started_at=second_started,
            ended_at=second_started + timedelta(milliseconds=10),
            latency_ms=10,
            method="POST",
            path="/v1/chat/completions",
            query=None,
            request_headers={"content-type": "application/json"},
            request_body_hash=shared_request_hash,
            response_status=200,
            response_headers={"content-type": "application/json"},
            model="gpt-4o-mini",
            usage=None,
            provider=None,
            response_body_hash=response_two,
        )
    )

    try:
        yield storage
    finally:
        await close_test_storage(storage, backend, schema)


async def _copy_run(
    storage: Storage,
    source_run_id: str,
    dest_run_id: str,
    *,
    step_count: int | None = None,
    step_overrides: dict[int, dict[str, object]] | None = None,
) -> None:
    steps = await storage.get_run(source_run_id)
    if step_count is not None:
        steps = steps[:step_count]
    for index, step in enumerate(steps, start=1):
        overrides = (step_overrides or {}).get(index, {})
        copied = step.model_copy(
            update={"id": uuid.uuid4().hex, "run_id": dest_run_id, **overrides},
        )
        await storage.save_exchange(copied)


@pytest.fixture
async def paired_runs_storage(baseline_storage: Storage) -> Storage:
    await _copy_run(baseline_storage, BASELINE_RUN_ID, CANDIDATE_RUN_ID)
    return baseline_storage


async def _create_test_via_api(
    storage: Storage,
    settings: Settings,
    *,
    name: str,
    baseline_run_id: str,
) -> httpx.Response:
    app = create_management_app(settings=settings, storage=storage)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://mgmt") as client:
            return await client.post(
                "/api/tests",
                json={"name": name, "baseline_run_id": baseline_run_id},
            )


@pytest.mark.asyncio
async def test_create_test_against_baseline_succeeds(
    baseline_storage: Storage,
    management_settings: Settings,
) -> None:
    response = await _create_test_via_api(
        baseline_storage,
        management_settings,
        name="clean baseline",
        baseline_run_id=BASELINE_RUN_ID,
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["baseline_run_id"] == BASELINE_RUN_ID
    assert payload["name"] == "clean baseline"


@pytest.mark.asyncio
async def test_create_test_against_missing_run_returns_404(
    baseline_storage: Storage,
    management_settings: Settings,
) -> None:
    response = await _create_test_via_api(
        baseline_storage,
        management_settings,
        name="missing baseline",
        baseline_run_id="does-not-exist",
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_run_regression_test_on_clean_baseline_passes(
    baseline_storage: Storage,
) -> None:
    test = RegressionTest(
        id=uuid.uuid4().hex,
        name="baseline check",
        baseline_run_id=BASELINE_RUN_ID,
        created_at=datetime.now(UTC),
    )
    await baseline_storage.save_test(test)

    result = await run_regression_test(baseline_storage, test)

    assert result.status == "pass"
    assert result.matched_steps == 3
    assert result.total_steps == 3
    assert result.first_divergent_step_index is None


@pytest.mark.asyncio
async def test_run_regression_test_reports_divergence(
    divergent_baseline_storage: Storage,
) -> None:
    test = RegressionTest(
        id=uuid.uuid4().hex,
        name="divergent baseline",
        baseline_run_id=BASELINE_RUN_ID,
        created_at=datetime.now(UTC),
    )
    await divergent_baseline_storage.save_test(test)

    result = await run_regression_test(divergent_baseline_storage, test)

    assert result.status == "fail"
    assert result.first_divergent_step_index == 2
    assert result.matched_steps == 1
    assert result.total_steps == 2


@pytest.mark.asyncio
async def test_control_api_create_run_and_list_results(
    baseline_storage: Storage,
    management_settings: Settings,
) -> None:
    app = create_management_app(settings=management_settings, storage=baseline_storage)
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://mgmt") as client:
            created = await client.post(
                "/api/tests",
                json={"name": "api test", "baseline_run_id": BASELINE_RUN_ID},
            )
            assert created.status_code == 201
            test_id = created.json()["id"]

            run_result = await client.post(f"/api/tests/{test_id}/run")
            assert run_result.status_code == 200
            assert run_result.json()["status"] == "pass"

            listed = await client.get("/api/tests")
            assert listed.status_code == 200
            assert listed.json()["total"] == 1

            detail = await client.get(f"/api/tests/{test_id}")
            assert detail.status_code == 200
            detail_payload = detail.json()
            assert detail_payload["id"] == test_id
            assert len(detail_payload["results"]) == 1
            assert detail_payload["results"][0]["status"] == "pass"


@pytest.mark.asyncio
async def test_compare_runs_on_identical_runs_passes(
    paired_runs_storage: Storage,
) -> None:
    result = await compare_runs(
        paired_runs_storage,
        BASELINE_RUN_ID,
        CANDIDATE_RUN_ID,
    )

    assert result.status == "pass"
    assert result.matched_steps == 3
    assert result.total_steps == 3
    assert len(result.step_diffs) == 3
    assert all(diff.request_match and diff.response_match for diff in result.step_diffs)


@pytest.mark.asyncio
async def test_compare_runs_fails_on_response_divergence(
    baseline_storage: Storage,
) -> None:
    wrong_response_hash = await baseline_storage.put_blob(b'{"id":"different"}')
    await _copy_run(
        baseline_storage,
        BASELINE_RUN_ID,
        CANDIDATE_RUN_ID,
        step_overrides={2: {"response_body_hash": wrong_response_hash}},
    )

    result = await compare_runs(
        baseline_storage,
        BASELINE_RUN_ID,
        CANDIDATE_RUN_ID,
    )

    assert result.status == "fail"
    assert result.first_divergent_step_index == 2
    assert result.step_diffs[1].request_match is True
    assert result.step_diffs[1].response_match is False
    assert "response_body_hash mismatch" in result.detail


@pytest.mark.asyncio
async def test_compare_runs_fails_on_request_divergence(
    baseline_storage: Storage,
) -> None:
    different_request_hash = await baseline_storage.put_blob(
        b'{"model":"gpt-4o-mini","messages":[{"role":"user","content":"other"}]}',
    )
    await _copy_run(
        baseline_storage,
        BASELINE_RUN_ID,
        CANDIDATE_RUN_ID,
        step_overrides={2: {"request_body_hash": different_request_hash}},
    )

    result = await compare_runs(
        baseline_storage,
        BASELINE_RUN_ID,
        CANDIDATE_RUN_ID,
    )

    assert result.status == "fail"
    assert result.first_divergent_step_index == 2
    assert result.step_diffs[1].request_match is False
    assert result.step_diffs[1].diff_kind == "request"
    assert "request" in result.detail


@pytest.mark.asyncio
async def test_compare_runs_fails_on_shorter_candidate(
    baseline_storage: Storage,
) -> None:
    await _copy_run(
        baseline_storage,
        BASELINE_RUN_ID,
        CANDIDATE_RUN_ID,
        step_count=2,
    )

    result = await compare_runs(
        baseline_storage,
        BASELINE_RUN_ID,
        CANDIDATE_RUN_ID,
    )

    assert result.status == "fail"
    assert result.first_divergent_step_index == 3
    assert "step count mismatch" in result.detail
    assert len(result.step_diffs) == 2
    assert all(diff.request_match and diff.response_match for diff in result.step_diffs)


@pytest.mark.asyncio
async def test_run_endpoint_with_candidate_run_id(
    baseline_storage: Storage,
    management_settings: Settings,
) -> None:
    await _copy_run(baseline_storage, BASELINE_RUN_ID, CANDIDATE_RUN_ID)
    app = create_management_app(settings=management_settings, storage=baseline_storage)
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://mgmt") as client:
            created = await client.post(
                "/api/tests",
                json={"name": "candidate compare", "baseline_run_id": BASELINE_RUN_ID},
            )
            test_id = created.json()["id"]

            run_result = await client.post(
                f"/api/tests/{test_id}/run",
                json={"candidate_run_id": CANDIDATE_RUN_ID},
            )
            assert run_result.status_code == 200
            payload = run_result.json()
            assert payload["status"] == "pass"
            assert payload["candidate_run_id"] == CANDIDATE_RUN_ID
            assert len(payload["step_diffs"]) == 3
            assert payload["step_diffs"][0]["request_match"] is True
            assert payload["step_diffs"][0]["response_match"] is True
