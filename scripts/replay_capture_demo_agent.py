"""CI replay-capture driver: same steps as demo_agent with OpenAI SDK JSON encoding."""

from __future__ import annotations

import sys

import httpx

from agent_steps import (
    demo_chat_steps,
    openai_chat_request_body,
    proxy_default_headers,
    resolve_proxy_base_url,
)


def main() -> None:
    proxy_v1 = resolve_proxy_base_url()
    proxy_root = proxy_v1[: -len("/v1")] if proxy_v1.endswith("/v1") else proxy_v1
    headers = {**proxy_default_headers(), "Content-Type": "application/json"}

    for step in demo_chat_steps():
        response = httpx.post(
            f"{proxy_root}/v1/chat/completions",
            content=openai_chat_request_body(step),
            headers=headers,
            timeout=30.0,
        )
        if response.status_code >= 400:
            print(response.text, file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
