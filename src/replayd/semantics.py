"""Extract and compare chat-completions semantics for regression testing."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from replayd.decoding import decode_body

DiffKind = str  # "none" | "wording" | "tool_call" | "finish_reason" | "structure" | "request"


class ToolCallSemantics(BaseModel):
    name: str
    argument_keys: tuple[str, ...] = ()


class ChoiceSemantics(BaseModel):
    finish_reason: str | None = None
    tool_calls: tuple[ToolCallSemantics, ...] = ()


class RequestSemantics(BaseModel):
    model: str | None = None
    message_roles: tuple[str, ...] = ()
    has_tools: bool = False
    has_functions: bool = False
    unparseable: bool = False


class ResponseSemantics(BaseModel):
    choices: tuple[ChoiceSemantics, ...] = ()
    unparseable: bool = False


class SemanticSummary(BaseModel):
    request: RequestSemantics
    response: ResponseSemantics
    response_contents: list[str | None] = Field(default_factory=list)
    unparseable: bool = False


def _parse_json(body: bytes) -> dict[str, Any] | None:
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _extract_argument_keys(arguments: Any) -> tuple[str, ...]:
    if isinstance(arguments, dict):
        return tuple(sorted(str(key) for key in arguments))
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return ()
        if isinstance(parsed, dict):
            return tuple(sorted(str(key) for key in parsed))
    return ()


def _normalize_tool_calls(message: dict[str, Any]) -> tuple[ToolCallSemantics, ...]:
    tool_calls: list[ToolCallSemantics] = []

    raw_tool_calls = message.get("tool_calls")
    if isinstance(raw_tool_calls, list):
        for item in raw_tool_calls:
            if not isinstance(item, dict):
                continue
            if item.get("type") not in (None, "function"):
                continue
            function = item.get("function")
            if not isinstance(function, dict):
                continue
            name = str(function.get("name") or "")
            tool_calls.append(
                ToolCallSemantics(
                    name=name,
                    argument_keys=_extract_argument_keys(function.get("arguments")),
                )
            )

    function_call = message.get("function_call")
    if isinstance(function_call, dict):
        name = str(function_call.get("name") or "")
        tool_calls.append(
            ToolCallSemantics(
                name=name,
                argument_keys=_extract_argument_keys(function_call.get("arguments")),
            )
        )

    tool_calls.sort(key=lambda item: (item.name, item.argument_keys))
    return tuple(tool_calls)


def _extract_request_semantics(request_body: bytes) -> RequestSemantics:
    payload = _parse_json(request_body)
    if payload is None:
        return RequestSemantics(unparseable=True)

    messages = payload.get("messages")
    roles: list[str] = []
    if isinstance(messages, list):
        for message in messages:
            if isinstance(message, dict):
                roles.append(str(message.get("role") or ""))

    tools = payload.get("tools")
    functions = payload.get("functions")
    return RequestSemantics(
        model=str(payload["model"]) if payload.get("model") is not None else None,
        message_roles=tuple(roles),
        has_tools=isinstance(tools, list) and len(tools) > 0,
        has_functions=isinstance(functions, list) and len(functions) > 0,
        unparseable=False,
    )


def _extract_response_semantics(
    response_body: bytes,
    response_headers: Mapping[str, str],
) -> tuple[ResponseSemantics, list[str | None]]:
    decoded = decode_body(response_body, response_headers)
    payload = _parse_json(decoded)
    if payload is None:
        return ResponseSemantics(unparseable=True), []

    raw_choices = payload.get("choices")
    if not isinstance(raw_choices, list):
        return ResponseSemantics(unparseable=True), []

    choices: list[ChoiceSemantics] = []
    contents: list[str | None] = []
    for choice in raw_choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if not isinstance(message, dict):
            message = {}
        content = message.get("content")
        contents.append(content if isinstance(content, str) else None)
        choices.append(
            ChoiceSemantics(
                finish_reason=(
                    str(choice["finish_reason"])
                    if choice.get("finish_reason") is not None
                    else None
                ),
                tool_calls=_normalize_tool_calls(message),
            )
        )

    return ResponseSemantics(choices=tuple(choices), unparseable=False), contents


def extract_semantics(
    request_body: bytes,
    response_body: bytes,
    response_headers: Mapping[str, str],
) -> SemanticSummary:
    try:
        request = _extract_request_semantics(request_body)
        response, response_contents = _extract_response_semantics(
            response_body,
            response_headers,
        )
        unparseable = request.unparseable or response.unparseable
        return SemanticSummary(
            request=request,
            response=response,
            response_contents=response_contents,
            unparseable=unparseable,
        )
    except Exception:
        return SemanticSummary(
            request=RequestSemantics(unparseable=True),
            response=ResponseSemantics(unparseable=True),
            response_contents=[],
            unparseable=True,
        )


def request_semantics_match(
    baseline: RequestSemantics,
    candidate: RequestSemantics,
) -> bool:
    if baseline.unparseable or candidate.unparseable:
        return False
    return (
        baseline.model == candidate.model
        and baseline.message_roles == candidate.message_roles
        and baseline.has_tools == candidate.has_tools
        and baseline.has_functions == candidate.has_functions
    )


def compare_response_semantics(
    baseline: ResponseSemantics,
    candidate: ResponseSemantics,
    *,
    baseline_contents: list[str | None],
    candidate_contents: list[str | None],
) -> tuple[bool, DiffKind]:
    if baseline.unparseable or candidate.unparseable:
        return False, "structure"

    if len(baseline.choices) != len(candidate.choices):
        return False, "structure"

    for baseline_choice, candidate_choice in zip(
        baseline.choices,
        candidate.choices,
        strict=True,
    ):
        if baseline_choice.finish_reason != candidate_choice.finish_reason:
            return False, "finish_reason"
        if baseline_choice.tool_calls != candidate_choice.tool_calls:
            return False, "tool_call"

    if baseline_contents != candidate_contents:
        return True, "wording"
    return True, "none"
