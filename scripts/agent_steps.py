"""Shared demo agent step definitions for record and replay scripts."""

from __future__ import annotations

from typing import Any

DEMO_MODEL = "gpt-4o-mini"
DEMO_MAX_TOKENS = 40

DEMO_STEP_PROMPTS = [
    "You are planning a short trip. In one sentence, name a city to visit.",
    "Now in one sentence, suggest one activity in that city.",
    "Now in one sentence, give a brief concluding tip for the trip.",
]

BRANCH_STEP_1_PROMPT = (
    "You are planning an adventure trip. In one sentence, name a mountain destination to visit."
)


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
