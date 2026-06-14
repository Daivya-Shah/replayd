import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

from replayd.models import Exchange, RegressionTest, StepDiff, TestResult
from replayd.semantics import (
    DiffKind,
    compare_response_semantics,
    extract_semantics,
    request_semantics_match,
)
from replayd.storage.base import Storage

logger = logging.getLogger(__name__)

ComparisonMode = Literal["exact", "semantic"]


def _find_matching_step(
    steps: list[Exchange],
    request_body_hash: str | None,
) -> Exchange | None:
    return next(
        (step for step in steps if step.request_body_hash == request_body_hash),
        None,
    )


def _comparison_detail(
    step_index: int,
    *,
    request_match: bool,
    response_match: bool,
    diff_kind: DiffKind,
    mode: ComparisonMode,
) -> str:
    if not request_match:
        return f"step {step_index}: request mismatch ({diff_kind})"
    if not response_match:
        if mode == "semantic":
            return f"step {step_index}: semantic response mismatch ({diff_kind})"
        return f"step {step_index}: response_body_hash mismatch"
    if diff_kind == "wording":
        return f"step {step_index}: wording differs but semantics match"
    return f"step {step_index}: regression check failed"


async def _load_step_bodies(
    storage: Storage,
    step: Exchange,
) -> tuple[bytes, bytes]:
    request_body = (
        await storage.get_blob(step.request_body_hash)
        if step.request_body_hash is not None
        else b""
    )
    response_body = (
        await storage.get_blob(step.response_body_hash)
        if step.response_body_hash is not None
        else b""
    )
    return request_body, response_body


async def _compare_step_exact(
    storage: Storage,
    baseline_step: Exchange,
    candidate_step: Exchange,
) -> tuple[bool, bool, DiffKind]:
    request_match = (
        baseline_step.request_body_hash == candidate_step.request_body_hash
    )
    response_match = (
        baseline_step.response_body_hash == candidate_step.response_body_hash
    )
    if request_match and response_match:
        return request_match, response_match, "none"
    if not request_match:
        return request_match, response_match, "request"
    return request_match, response_match, "structure"


async def _compare_step_semantic(
    storage: Storage,
    baseline_step: Exchange,
    candidate_step: Exchange,
) -> tuple[bool, bool, DiffKind]:
    baseline_request, baseline_response = await _load_step_bodies(
        storage,
        baseline_step,
    )
    candidate_request, candidate_response = await _load_step_bodies(
        storage,
        candidate_step,
    )

    baseline_summary = extract_semantics(
        baseline_request,
        baseline_response,
        baseline_step.response_headers,
    )
    candidate_summary = extract_semantics(
        candidate_request,
        candidate_response,
        candidate_step.response_headers,
    )

    request_match = request_semantics_match(
        baseline_summary.request,
        candidate_summary.request,
    )
    if not request_match:
        return False, False, "request"

    response_match, diff_kind = compare_response_semantics(
        baseline_summary.response,
        candidate_summary.response,
        baseline_contents=baseline_summary.response_contents,
        candidate_contents=candidate_summary.response_contents,
    )
    return request_match, response_match, diff_kind


async def compare_runs(
    storage: Storage,
    baseline_run_id: str,
    candidate_run_id: str,
    *,
    mode: ComparisonMode = "exact",
) -> TestResult:
    run_at = datetime.now(UTC)
    result_id = uuid.uuid4().hex
    baseline_steps = await storage.get_run(baseline_run_id)
    candidate_steps = await storage.get_run(candidate_run_id)

    if not baseline_steps:
        return TestResult(
            id=result_id,
            test_id="",
            run_at=run_at,
            status="fail",
            total_steps=0,
            matched_steps=0,
            first_divergent_step_index=None,
            detail="baseline run not found",
            candidate_run_id=candidate_run_id,
        )

    if not candidate_steps:
        return TestResult(
            id=result_id,
            test_id="",
            run_at=run_at,
            status="fail",
            total_steps=len(baseline_steps),
            matched_steps=0,
            first_divergent_step_index=1,
            detail="candidate run not found",
            candidate_run_id=candidate_run_id,
        )

    baseline_len = len(baseline_steps)
    candidate_len = len(candidate_steps)
    compare_len = min(baseline_len, candidate_len)
    step_diffs: list[StepDiff] = []
    matched_steps = 0
    first_divergent_step_index: int | None = None
    detail = "all steps matched"

    compare_step = _compare_step_exact if mode == "exact" else _compare_step_semantic

    for step_index in range(1, compare_len + 1):
        baseline_step = baseline_steps[step_index - 1]
        candidate_step = candidate_steps[step_index - 1]
        request_match, response_match, diff_kind = await compare_step(
            storage,
            baseline_step,
            candidate_step,
        )
        step_diffs.append(
            StepDiff(
                step_index=step_index,
                request_match=request_match,
                response_match=response_match,
                diff_kind=diff_kind,
            )
        )

        if request_match and response_match:
            matched_steps += 1
            continue

        first_divergent_step_index = step_index
        detail = _comparison_detail(
            step_index,
            request_match=request_match,
            response_match=response_match,
            diff_kind=diff_kind,
            mode=mode,
        )
        break

    if first_divergent_step_index is None and baseline_len != candidate_len:
        first_divergent_step_index = compare_len + 1
        detail = (
            f"step count mismatch: baseline has {baseline_len} steps, "
            f"candidate has {candidate_len} steps"
        )

    status = (
        "pass"
        if matched_steps == baseline_len and baseline_len == candidate_len
        else "fail"
    )

    return TestResult(
        id=result_id,
        test_id="",
        run_at=run_at,
        status=status,
        total_steps=baseline_len,
        matched_steps=matched_steps,
        first_divergent_step_index=first_divergent_step_index if status == "fail" else None,
        detail=detail,
        candidate_run_id=candidate_run_id,
        step_diffs=step_diffs,
    )


async def _run_self_baseline_check(
    storage: Storage,
    test: RegressionTest,
    *,
    result_id: str,
    run_at: datetime,
) -> TestResult:
    steps = await storage.get_run(test.baseline_run_id)

    if not steps:
        return TestResult(
            id=result_id,
            test_id=test.id,
            run_at=run_at,
            status="fail",
            total_steps=0,
            matched_steps=0,
            first_divergent_step_index=None,
            detail="baseline run not found",
        )

    total_steps = len(steps)
    matched_steps = 0
    first_divergent_step_index: int | None = None
    detail = "all steps matched"

    for step_index, baseline_step in enumerate(steps, start=1):
        request_hash = baseline_step.request_body_hash
        if request_hash is not None:
            await storage.get_blob(request_hash)

        matched = _find_matching_step(steps, request_hash)
        if matched is None:
            first_divergent_step_index = step_index
            detail = f"step {step_index}: no recorded request match for request_body_hash"
            break

        if matched.response_body_hash != baseline_step.response_body_hash:
            first_divergent_step_index = step_index
            detail = (
                f"step {step_index}: response_body_hash mismatch "
                f"(expected {baseline_step.response_body_hash}, got {matched.response_body_hash})"
            )
            break

        matched_steps += 1

    status = "pass" if matched_steps == total_steps else "fail"
    if status == "fail" and first_divergent_step_index is None:
        first_divergent_step_index = matched_steps + 1
        detail = f"step {first_divergent_step_index}: regression check failed"

    return TestResult(
        id=result_id,
        test_id=test.id,
        run_at=run_at,
        status=status,
        total_steps=total_steps,
        matched_steps=matched_steps,
        first_divergent_step_index=first_divergent_step_index if status == "fail" else None,
        detail=detail,
    )


async def run_regression_test(
    storage: Storage,
    test: RegressionTest,
    candidate_run_id: str | None = None,
) -> TestResult:
    run_at = datetime.now(UTC)
    result_id = uuid.uuid4().hex

    if candidate_run_id is not None:
        result = await compare_runs(
            storage,
            test.baseline_run_id,
            candidate_run_id,
            mode=test.mode,  # type: ignore[arg-type]
        )
        result = result.model_copy(
            update={"id": result_id, "test_id": test.id, "run_at": run_at},
        )
    else:
        result = await _run_self_baseline_check(
            storage,
            test,
            result_id=result_id,
            run_at=run_at,
        )

    await storage.save_test_result(result)

    logger.info(
        "regression test completed",
        extra={
            "test_id": test.id,
            "status": result.status,
            "matched_steps": result.matched_steps,
            "total_steps": result.total_steps,
            "candidate_run_id": candidate_run_id,
            "mode": test.mode,
        },
    )
    return result
