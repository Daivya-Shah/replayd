from collections.abc import Mapping

REDACTED_VALUE = "[REDACTED]"

SENSITIVE_HEADER_NAMES = frozenset(
    {
        "authorization",
        "x-api-key",
        "api-key",
        "cookie",
        "set-cookie",
        "openai-organization",
        "proxy-authorization",
    }
)


def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    redacted: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in SENSITIVE_HEADER_NAMES:
            redacted[key] = REDACTED_VALUE
        else:
            redacted[key] = value
    return redacted
