"""Shared demo agent step definitions for record and replay scripts."""

from __future__ import annotations

import os
from typing import Any

DEMO_MODEL = "gpt-4o-mini"
DEMO_MAX_TOKENS = 40

REPLAYD_INGEST_KEY_ENV = "REPLAYD_INGEST_KEY"
REPLAYD_BASE_URL_ENV = "REPLAYD_BASE_URL"
REPLAYD_PROXY_URL_ENV = "REPLAYD_PROXY_URL"
REPLAYD_REPLAY_RUN_ID_ENV = "REPLAYD_REPLAY_RUN_ID"
REPLAYD_RUN_ID_ENV = "REPLAYD_RUN_ID"

INGEST_KEY_HEADER = "x-replayd-key"
REPLAY_HEADER = "x-replayd-replay"
RUN_ID_HEADER = "x-replayd-run-id"
DEFAULT_PROXY_BASE_URL = "http://localhost:8787/v1"

DEMO_STEP_PROMPTS = [
    "You are planning a short trip. In one sentence, name a city to visit.",
    "Now in one sentence, suggest one activity in that city.",
    "Now in one sentence, give a brief concluding tip for the trip.",
]

BRANCH_STEP_1_PROMPT = (
    "You are planning an adventure trip. In one sentence, name a mountain destination to visit."
)


def resolve_proxy_base_url() -> str:
    for env_name in (REPLAYD_BASE_URL_ENV, REPLAYD_PROXY_URL_ENV):
        value = os.environ.get(env_name)
        if value:
            normalized = value.rstrip("/")
            if not normalized.endswith("/v1"):
                return f"{normalized}/v1"
            return normalized
    return DEFAULT_PROXY_BASE_URL


def proxy_default_headers(**overrides: str) -> dict[str, str]:
    """Build proxy control headers from environment and optional overrides."""
    headers: dict[str, str] = {}

    replay_run_id = os.environ.get(REPLAYD_REPLAY_RUN_ID_ENV)
    if replay_run_id:
        headers[REPLAY_HEADER] = replay_run_id

    run_id = os.environ.get(REPLAYD_RUN_ID_ENV)
    if run_id:
        headers[RUN_ID_HEADER] = run_id

    ingest_key = os.environ.get(REPLAYD_INGEST_KEY_ENV)
    if ingest_key:
        headers[INGEST_KEY_HEADER] = ingest_key

    headers.update(overrides)
    return headers


def demo_chat_steps() -> list[dict[str, Any]]:
    return [
        {
            "model": DEMO_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": DEMO_MAX_TOKENS,
        }
        for prompt in DEMO_STEP_PROMPTS
    ]


def branch_chat_steps() -> list[dict[str, Any]]:
    prompts = [BRANCH_STEP_1_PROMPT, DEMO_STEP_PROMPTS[1], DEMO_STEP_PROMPTS[2]]
    return [
        {
            "model": DEMO_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": DEMO_MAX_TOKENS,
        }
        for prompt in prompts
    ]


def run_branch_chat_steps(
    client: Any,
    *,
    extra_headers: dict[str, str] | None = None,
) -> list[str]:
    replies: list[str] = []
    for step in branch_chat_steps():
        response = client.chat.completions.create(
            **step,
            extra_headers=extra_headers,
        )
        replies.append(response.choices[0].message.content or "")
    return replies


def run_demo_chat_steps(
    client: Any,
    *,
    extra_headers: dict[str, str] | None = None,
) -> list[str]:
    replies: list[str] = []
    for step in demo_chat_steps():
        response = client.chat.completions.create(
            **step,
            extra_headers=extra_headers,
        )
        replies.append(response.choices[0].message.content or "")
    return replies
