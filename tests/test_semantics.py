import gzip
import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from replayd.management import create_management_app
from replayd.models import Exchange
from replayd.semantics import (
    compare_response_semantics,
    extract_semantics,
    request_semantics_match,
)
from replayd.storage.base import Storage
from replayd.testing import compare_runs
from db_backends import close_test_storage, dual_params, open_test_storage

SAMPLE_REQUEST = json.dumps(
    {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "What is 2+2?"},
        ],
        "tools": [{"type": "function", "function": {"name": "calc"}}],
    }
).encode()

SAMPLE_RESPONSE = json.dumps(
    {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "calc",
                                "arguments": '{"expression":"2+2"}',
                            },
                        }
                    ],
                },
            }
        ]
    }
).encode()

BASELINE_RUN_ID = "baseline-run"
CANDIDATE_RUN_ID = "candidate-run"


async def _seed_single_step_run(
    storage: Storage,
    run_id: str,
    *,
    request_body: bytes,
    response_body: bytes,
    exchange_id: str | None = None,
) -> None:
    started_at = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)
    request_hash = await storage.put_blob(request_body)
    response_hash = await storage.put_blob(response_body)
    await storage.save_exchange(
        Exchange(
            id=exchange_id or uuid.uuid4().hex,
            run_id=run_id,
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
            request_body_hash=request_hash,
            response_status=200,
            response_headers={"content-type": "application/json"},
            model="gpt-4o-mini",
            usage=None,
            provider=None,
            response_body_hash=response_hash,
        )
    )


@pytest.fixture(params=dual_params())
async def comparison_storage(request: pytest.FixtureRequest, tmp_path):
    backend: str = request.param
    storage, schema = await open_test_storage(backend, tmp_path)
    try:
        yield storage
    finally:
        await close_test_storage(storage, backend, schema)


def test_extract_semantics_parses_tool_call_and_finish_reason() -> None:
    summary = extract_semantics(SAMPLE_REQUEST, SAMPLE_RESPONSE, {})

    assert summary.request.model == "gpt-4o-mini"
    assert summary.request.message_roles == ("system", "user")
    assert summary.request.has_tools is True
    assert summary.request.has_functions is False
    assert summary.unparseable is False

    assert len(summary.response.choices) == 1
    choice = summary.response.choices[0]
    assert choice.finish_reason == "tool_calls"
    assert len(choice.tool_calls) == 1
    assert choice.tool_calls[0].name == "calc"
    assert choice.tool_calls[0].argument_keys == ("expression",)


def test_extract_semantics_handles_gzip() -> None:
    compressed = gzip.compress(SAMPLE_RESPONSE)
    headers = {"content-encoding": "gzip"}

    summary = extract_semantics(SAMPLE_REQUEST, compressed, headers)

    assert summary.unparseable is False
    assert summary.response.choices[0].finish_reason == "tool_calls"
    assert summary.response.choices[0].tool_calls[0].name == "calc"


def test_extract_semantics_never_raises_on_garbage() -> None:
    summary = extract_semantics(b"not-json", b"\x00\xff\xfe", {})

    assert summary.unparseable is True
    assert summary.request.unparseable is True
    assert summary.response.unparseable is True


def test_semantic_compare_passes_on_wording_difference() -> None:
    baseline_response = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "Paris is a lovely city."},
                }
            ]
        }
    ).encode()
    candidate_response = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "Paris is wonderful for visitors."},
                }
            ]
        }
    ).encode()

    baseline = extract_semantics(SAMPLE_REQUEST, baseline_response, {})
    candidate = extract_semantics(SAMPLE_REQUEST, candidate_response, {})

    response_match, diff_kind = compare_response_semantics(
        baseline.response,
        candidate.response,
        baseline_contents=baseline.response_contents,
        candidate_contents=candidate.response_contents,
    )

    assert response_match is True
    assert diff_kind == "wording"


def test_request_semantics_match_ignores_message_content() -> None:
    baseline_request = json.dumps(
        {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hello"}],
        }
    ).encode()
    candidate_request = json.dumps(
        {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "goodbye"}],
        }
    ).encode()

    baseline = extract_semantics(baseline_request, SAMPLE_RESPONSE, {})
    candidate = extract_semantics(candidate_request, SAMPLE_RESPONSE, {})

    assert request_semantics_match(baseline.request, candidate.request) is True


@pytest.mark.asyncio
async def test_semantic_compare_passes_on_same_tool_different_argument_values(
    comparison_storage: Storage,
) -> None:
    request_body = json.dumps(
        {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "search"}],
        }
    ).encode()
    baseline_response = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "search",
                                    "arguments": '{"query":"hotels"}',
                                },
                            }
                        ]
                    },
                }
            ]
        }
    ).encode()
    candidate_response = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "search",
                                    "arguments": '{"query":"flights"}',
                                },
                            }
                        ]
                    },
                }
            ]
        }
    ).encode()

    await _seed_single_step_run(
        comparison_storage,
        BASELINE_RUN_ID,
        request_body=request_body,
        response_body=baseline_response,
    )
    await _seed_single_step_run(
        comparison_storage,
        CANDIDATE_RUN_ID,
        request_body=request_body,
        response_body=candidate_response,
    )

    result = await compare_runs(
        comparison_storage,
        BASELINE_RUN_ID,
        CANDIDATE_RUN_ID,
        mode="semantic",
    )

    assert result.status == "pass"
    assert result.step_diffs[0].response_match is True
    assert result.step_diffs[0].diff_kind in {"wording", "none"}


@pytest.mark.asyncio
async def test_semantic_compare_fails_on_different_tool_name(
    comparison_storage: Storage,
) -> None:
    request_body = json.dumps(
        {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "act"}],
        }
    ).encode()
    baseline_response = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "search",
                                    "arguments": '{"q":"a"}',
                                },
                            }
                        ]
                    },
                }
            ]
        }
    ).encode()
    candidate_response = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "book",
                                    "arguments": '{"q":"a"}',
                                },
                            }
                        ]
                    },
                }
            ]
        }
    ).encode()

    await _seed_single_step_run(
        comparison_storage,
        BASELINE_RUN_ID,
        request_body=request_body,
        response_body=baseline_response,
    )
    await _seed_single_step_run(
        comparison_storage,
        CANDIDATE_RUN_ID,
        request_body=request_body,
        response_body=candidate_response,
    )

    result = await compare_runs(
        comparison_storage,
        BASELINE_RUN_ID,
        CANDIDATE_RUN_ID,
        mode="semantic",
    )

    assert result.status == "fail"
    assert result.first_divergent_step_index == 1
    assert result.step_diffs[0].diff_kind == "tool_call"
    assert result.step_diffs[0].response_match is False


@pytest.mark.asyncio
async def test_semantic_compare_fails_on_different_finish_reason(
    comparison_storage: Storage,
) -> None:
    request_body = json.dumps(
        {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "go"}],
        }
    ).encode()
    baseline_response = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "done"},
                }
            ]
        }
    ).encode()
    candidate_response = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": "done"},
                }
            ]
        }
    ).encode()

    await _seed_single_step_run(
        comparison_storage,
        BASELINE_RUN_ID,
        request_body=request_body,
        response_body=baseline_response,
    )
    await _seed_single_step_run(
        comparison_storage,
        CANDIDATE_RUN_ID,
        request_body=request_body,
        response_body=candidate_response,
    )

    result = await compare_runs(
        comparison_storage,
        BASELINE_RUN_ID,
        CANDIDATE_RUN_ID,
        mode="semantic",
    )

    assert result.status == "fail"
    assert result.step_diffs[0].diff_kind == "finish_reason"


@pytest.mark.asyncio
async def test_exact_mode_still_fails_on_byte_difference(
    comparison_storage: Storage,
) -> None:
    request_body = json.dumps(
        {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "step 1"}],
        }
    ).encode()
    baseline_response = b'{"id":"r1","choices":[{"message":{"content":"reply 1"}}]}'
    candidate_response = b'{"id":"r2","choices":[{"message":{"content":"reply 1"}}]}'

    await _seed_single_step_run(
        comparison_storage,
        BASELINE_RUN_ID,
        request_body=request_body,
        response_body=baseline_response,
    )
    await _seed_single_step_run(
        comparison_storage,
        CANDIDATE_RUN_ID,
        request_body=request_body,
        response_body=candidate_response,
    )

    result = await compare_runs(
        comparison_storage,
        BASELINE_RUN_ID,
        CANDIDATE_RUN_ID,
        mode="exact",
    )

    assert result.status == "fail"
    assert result.step_diffs[0].response_match is False


@pytest.mark.asyncio
async def test_run_endpoint_uses_test_mode_semantic(
    comparison_storage: Storage,
) -> None:
    from replayd.config import Settings

    request_body = json.dumps(
        {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        }
    ).encode()
    baseline_response = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "Hello there."},
                }
            ]
        }
    ).encode()
    candidate_response = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "Hi back."},
                }
            ]
        }
    ).encode()

    await _seed_single_step_run(
        comparison_storage,
        BASELINE_RUN_ID,
        request_body=request_body,
        response_body=baseline_response,
    )
    await _seed_single_step_run(
        comparison_storage,
        CANDIDATE_RUN_ID,
        request_body=request_body,
        response_body=candidate_response,
    )

    settings = Settings(STORAGE_DIR="./data", MGMT_CORS_ORIGIN="http://localhost:3000")
    app = create_management_app(settings=settings, storage=comparison_storage)
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://mgmt") as client:
            created = await client.post(
                "/api/tests",
                json={
                    "name": "semantic api",
                    "baseline_run_id": BASELINE_RUN_ID,
                    "mode": "semantic",
                },
            )
            test_id = created.json()["id"]
            run_result = await client.post(
                f"/api/tests/{test_id}/run",
                json={"candidate_run_id": CANDIDATE_RUN_ID},
            )

    payload = run_result.json()
    assert payload["status"] == "pass"
    assert payload["step_diffs"][0]["diff_kind"] == "wording"
    assert payload["step_diffs"][0]["response_match"] is True
