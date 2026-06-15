import hashlib
import json
import logging
import uuid
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime

import httpx
from fastapi import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from replayd.config import Settings, get_settings
from replayd.models import Exchange
from replayd.redaction import redact_headers
from replayd.storage.base import Storage
from replayd.tenancy import DEFAULT_PROJECT_ID

logger = logging.getLogger(__name__)

HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)

PROXY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


def _connection_header_names(headers: Mapping[str, str]) -> set[str]:
    for key, value in headers.items():
        if key.lower() == "connection":
            return {part.strip().lower() for part in value.split(",") if part.strip()}
    return set()


def _is_replayd_control_header(header_name: str) -> bool:
    return header_name.lower().startswith("x-replayd-")


def filter_request_headers(headers: Mapping[str, str]) -> dict[str, str]:
    connection_headers = _connection_header_names(headers)
    filtered: dict[str, str] = {}
    for key, value in headers.items():
        lower = key.lower()
        if lower == "host" or lower == "content-length":
            continue
        if _is_replayd_control_header(lower):
            continue
        if lower in HOP_BY_HOP_HEADERS or lower in connection_headers:
            continue
        filtered[key] = value
    return filtered


def filter_response_headers(headers: Mapping[str, str]) -> dict[str, str]:
    connection_headers = _connection_header_names(headers)
    filtered: dict[str, str] = {}
    for key, value in headers.items():
        lower = key.lower()
        if lower in HOP_BY_HOP_HEADERS or lower in connection_headers:
            continue
        filtered[key] = value
    return filtered


def _header_value_from_headers(headers: Mapping[str, str], header_name: str) -> str | None:
    value = headers.get(header_name)
    if value is not None and value.strip():
        return value.strip()
    target = header_name.lower()
    for key, header_value in headers.items():
        if key.lower() == target and header_value.strip():
            return header_value.strip()
    return None


def _header_value_from_scope(scope: dict[str, object], header_name: str) -> str | None:
    raw_headers = scope.get("headers")
    if not isinstance(raw_headers, list):
        return None
    target = header_name.lower().encode("latin-1")
    for raw_key, raw_value in raw_headers:
        if not isinstance(raw_key, bytes) or not isinstance(raw_value, bytes):
            continue
        if raw_key.lower() == target:
            decoded = raw_value.decode("latin-1").strip()
            if decoded:
                return decoded
    return None


def resolve_replay_run_id(request: Request, settings: Settings) -> str | None:
    header_name = settings.REPLAY_HEADER
    value = _header_value_from_scope(request.scope, header_name)
    if value is not None:
        return value
    return _header_value_from_headers(request.headers, header_name)


def resolve_branch_parent_run_id(request: Request, settings: Settings) -> str | None:
    header_name = settings.BRANCH_HEADER
    value = _header_value_from_scope(request.scope, header_name)
    if value is not None:
        return value
    return _header_value_from_headers(request.headers, header_name)


def resolve_run_id_from_request(request: Request, settings: Settings) -> str:
    header_name = settings.RUN_ID_HEADER
    value = _header_value_from_scope(request.scope, header_name)
    if value is None:
        value = _header_value_from_headers(request.headers, header_name)
    return value or uuid.uuid4().hex


def resolve_candidate_run_id(request: Request, settings: Settings) -> str | None:
    """Return an explicit capture run id from RUN_ID_HEADER, or None if absent."""
    header_name = settings.RUN_ID_HEADER
    value = _header_value_from_scope(request.scope, header_name)
    if value is not None:
        return value
    return _header_value_from_headers(request.headers, header_name)


def _run_id_from_headers(headers: Mapping[str, str], header_name: str) -> str | None:
    return _header_value_from_headers(headers, header_name)


def is_replay_request(request: Request, settings: Settings) -> bool:
    return resolve_replay_run_id(request, settings) is not None


def request_body_hash(body: bytes) -> str | None:
    if not body:
        return None
    return hashlib.sha256(body).hexdigest()


def _headers_to_dict(headers: Mapping[str, str]) -> dict[str, str]:
    return {key: value for key, value in headers.items()}


def _resolve_run_id(request: Request, run_id_header: str) -> str:
    return _run_id_from_headers(request.headers, run_id_header) or uuid.uuid4().hex


def _resolve_run_id_header(request: Request) -> str:
    app = request.scope.get("app")
    if app is not None:
        return app.state.settings.RUN_ID_HEADER
    return "x-replayd-run-id"


def _extract_model(request_body: bytes) -> str | None:
    try:
        payload = json.loads(request_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    model = payload.get("model")
    return model if isinstance(model, str) else None


def _extract_usage(
    response_body: bytes,
    response_headers: Mapping[str, str],
) -> dict | None:
    content_type = next(
        (value for key, value in response_headers.items() if key.lower() == "content-type"),
        None,
    )
    if content_type is None or "application/json" not in content_type.lower():
        return None
    try:
        payload = json.loads(response_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    usage = payload.get("usage")
    return usage if isinstance(usage, dict) else None


def _settings_from_request(request: Request) -> Settings:
    app = request.scope.get("app")
    if app is not None and hasattr(app.state, "settings"):
        return app.state.settings
    return get_settings()


def _ingest_key_rejection_response() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"error": "invalid_or_missing_ingest_key"},
    )


async def resolve_capture_project_id(
    request: Request,
    storage: Storage,
    settings: Settings,
) -> str | Response:
    """Resolve the project to attribute captured traffic to.

    Returns a Response (401) only when REQUIRE_INGEST_KEY is true and the key
    is missing or invalid. Storage errors are logged; lenient mode falls back to
    DEFAULT_PROJECT_ID so the forwarded request can still succeed.
    """
    plaintext = _header_value_from_scope(request.scope, settings.INGEST_KEY_HEADER)
    if plaintext is None:
        plaintext = _header_value_from_headers(request.headers, settings.INGEST_KEY_HEADER)

    if not plaintext:
        if settings.REQUIRE_INGEST_KEY:
            return _ingest_key_rejection_response()
        return DEFAULT_PROJECT_ID

    try:
        matched = await storage.resolve_ingest_key(plaintext)
    except Exception:
        logger.exception("failed to resolve ingest key")
        if settings.REQUIRE_INGEST_KEY:
            return _ingest_key_rejection_response()
        return DEFAULT_PROJECT_ID

    if matched is None:
        if settings.REQUIRE_INGEST_KEY:
            return _ingest_key_rejection_response()
        return DEFAULT_PROJECT_ID

    try:
        await storage.touch_ingest_key(matched.id)
    except Exception:
        logger.exception("failed to update ingest key last_used_at")

    return matched.project_id


async def persist_exchange(
    storage: Storage,
    *,
    request: Request,
    request_body: bytes,
    started_at: datetime,
    ended_at: datetime,
    response_status: int,
    response_headers: Mapping[str, str],
    response_body: bytes,
    run_id: str,
    parent_run_id: str | None,
    origin: str,
    project_id: str,
) -> None:
    created_at = datetime.now(UTC)
    request_body_hash = await storage.put_blob(request_body) if request_body else None
    response_body_hash = await storage.put_blob(response_body) if response_body else None
    latency_ms = max(0, int((ended_at - started_at).total_seconds() * 1000))

    exchange = Exchange(
        id=uuid.uuid4().hex,
        project_id=project_id,
        run_id=run_id,
        parent_run_id=parent_run_id,
        origin=origin,
        created_at=created_at,
        started_at=started_at,
        ended_at=ended_at,
        latency_ms=latency_ms,
        method=request.method,
        path=request.url.path,
        query=request.url.query or None,
        request_headers=redact_headers(_headers_to_dict(request.headers)),
        request_body_hash=request_body_hash,
        response_status=response_status,
        response_headers=redact_headers(_headers_to_dict(response_headers)),
        model=_extract_model(request_body),
        usage=_extract_usage(response_body, response_headers),
        provider=None,
        response_body_hash=response_body_hash,
    )
    await storage.save_exchange(exchange)


async def replay_request(
    request: Request,
    storage: Storage | None,
    settings: Settings,
) -> Response:
    if storage is None:
        return JSONResponse(
            status_code=500,
            content={"error": "replay requires storage"},
        )

    baseline_run_id = resolve_replay_run_id(request, settings)
    if baseline_run_id is None:
        return JSONResponse(
            status_code=400,
            content={"error": "replay header missing or empty"},
        )

    candidate_run_id = resolve_candidate_run_id(request, settings)
    body = await request.body()
    body_hash = request_body_hash(body)

    logger.info(
        "replay request",
        extra={
            "method": request.method,
            "path": request.url.path,
            "run_id": baseline_run_id,
            "candidate_run_id": candidate_run_id,
            "request_body_hash": body_hash,
        },
    )

    steps = await storage.get_run(baseline_run_id)
    if not steps:
        return JSONResponse(
            status_code=404,
            content={"error": "run_not_found", "run_id": baseline_run_id},
        )

    matched = next(
        (step for step in steps if step.request_body_hash == body_hash),
        None,
    )
    if matched is None:
        return JSONResponse(
            status_code=422,
            content={
                "error": "replay_divergence",
                "detail": "no recorded response matches this request",
                "run_id": baseline_run_id,
                "request_body_hash": body_hash,
            },
        )

    if matched.response_body_hash is None:
        response_body = b""
    else:
        response_body = await storage.get_blob(matched.response_body_hash)

    if candidate_run_id is not None:
        capture_project_id = await resolve_capture_project_id(request, storage, settings)
        if isinstance(capture_project_id, Response):
            return capture_project_id

        started_at = datetime.now(UTC)
        ended_at = datetime.now(UTC)
        try:
            await persist_exchange(
                storage,
                request=request,
                request_body=body,
                started_at=started_at,
                ended_at=ended_at,
                response_status=matched.response_status,
                response_headers=matched.response_headers,
                response_body=response_body,
                run_id=candidate_run_id,
                parent_run_id=baseline_run_id,
                origin="replayed",
                project_id=capture_project_id,
            )
        except Exception:
            logger.exception("failed to capture replay exchange")

    return Response(
        content=response_body,
        status_code=matched.response_status,
        headers=filter_response_headers(matched.response_headers),
    )


async def branch_request(
    request: Request,
    client: httpx.AsyncClient,
    storage: Storage | None,
    settings: Settings,
) -> Response:
    if storage is None:
        return JSONResponse(
            status_code=500,
            content={"error": "branch requires storage"},
        )

    parent_run_id = resolve_branch_parent_run_id(request, settings)
    if parent_run_id is None:
        return JSONResponse(
            status_code=400,
            content={"error": "branch header missing or empty"},
        )

    capture_project_id = await resolve_capture_project_id(request, storage, settings)
    if isinstance(capture_project_id, Response):
        return capture_project_id

    branch_run_id = resolve_run_id_from_request(request, settings)
    body = await request.body()
    body_hash = request_body_hash(body)

    logger.info(
        "branch request",
        extra={
            "method": request.method,
            "path": request.url.path,
            "parent_run_id": parent_run_id,
            "branch_run_id": branch_run_id,
            "request_body_hash": body_hash,
        },
    )

    parent_steps = await storage.get_run(parent_run_id)
    if not parent_steps:
        return JSONResponse(
            status_code=404,
            content={"error": "run_not_found", "run_id": parent_run_id},
        )

    matched = next(
        (step for step in parent_steps if step.request_body_hash == body_hash),
        None,
    )

    started_at = datetime.now(UTC)

    if matched is not None:
        if matched.response_body_hash is None:
            response_body = b""
        else:
            response_body = await storage.get_blob(matched.response_body_hash)
        ended_at = datetime.now(UTC)
        try:
            await persist_exchange(
                storage,
                request=request,
                request_body=body,
                started_at=started_at,
                ended_at=ended_at,
                response_status=matched.response_status,
                response_headers=matched.response_headers,
                response_body=response_body,
                run_id=branch_run_id,
                parent_run_id=parent_run_id,
                origin="replayed",
                project_id=capture_project_id,
            )
        except Exception:
            logger.exception("failed to capture branch exchange")

        return Response(
            content=response_body,
            status_code=matched.response_status,
            headers=filter_response_headers(matched.response_headers),
        )

    return await forward_request(
        request,
        client,
        storage=storage,
        settings=settings,
        request_body=body,
        capture_run_id=branch_run_id,
        capture_parent_run_id=parent_run_id,
        capture_origin="live",
        project_id=capture_project_id,
    )


async def forward_request(
    request: Request,
    client: httpx.AsyncClient,
    storage: Storage | None = None,
    *,
    settings: Settings | None = None,
    capture: bool = True,
    request_body: bytes | None = None,
    capture_run_id: str | None = None,
    capture_parent_run_id: str | None = None,
    capture_origin: str = "live",
    project_id: str | None = None,
) -> Response:
    resolved_settings = settings or _settings_from_request(request)

    capture_project_id = project_id
    if capture_project_id is None:
        if storage is not None:
            resolved = await resolve_capture_project_id(
                request,
                storage,
                resolved_settings,
            )
            if isinstance(resolved, Response):
                return resolved
            capture_project_id = resolved
        elif resolved_settings.REQUIRE_INGEST_KEY:
            return _ingest_key_rejection_response()
        else:
            capture_project_id = DEFAULT_PROJECT_ID

    url = request.url.path
    if request.url.query:
        url = f"{url}?{request.url.query}"

    headers = filter_request_headers(request.headers)
    body = request_body if request_body is not None else await request.body()

    logger.info(
        "proxying request",
        extra={
            "method": request.method,
            "path": request.url.path,
            "upstream_url": url,
        },
    )

    should_capture = storage is not None and capture
    started_at = datetime.now(UTC) if should_capture else None
    run_id_header = _resolve_run_id_header(request) if should_capture else ""
    capture_run = capture_run_id
    if should_capture and capture_run is None:
        capture_run = _resolve_run_id(request, run_id_header)
    # TODO: stream large response bodies to disk instead of buffering in memory (v0).
    response_buffer = bytearray() if should_capture else None

    stream_cm = client.stream(
        method=request.method,
        url=url,
        headers=headers,
        content=body,
    )
    try:
        upstream = await stream_cm.__aenter__()
    except BaseException:
        await stream_cm.__aexit__(None, None, None)
        raise

    async def stream_body() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_raw():
                if response_buffer is not None:
                    response_buffer.extend(chunk)
                yield chunk
        finally:
            await stream_cm.__aexit__(None, None, None)
            if should_capture and started_at is not None and response_buffer is not None:
                try:
                    await persist_exchange(
                        storage,
                        request=request,
                        request_body=body,
                        started_at=started_at,
                        ended_at=datetime.now(UTC),
                        response_status=upstream.status_code,
                        response_headers=upstream.headers,
                        response_body=bytes(response_buffer),
                        run_id=capture_run or uuid.uuid4().hex,
                        parent_run_id=capture_parent_run_id,
                        origin=capture_origin,
                        project_id=capture_project_id,
                    )
                except Exception:
                    logger.exception("failed to capture exchange")

    return StreamingResponse(
        stream_body(),
        status_code=upstream.status_code,
        headers=filter_response_headers(upstream.headers),
    )
