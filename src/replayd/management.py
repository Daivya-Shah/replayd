import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.responses import JSONResponse, Response

from replayd.check_oidc import OidcConnectivityError, verify_oidc_connectivity
from replayd.config import Settings, get_settings
from replayd.control_auth import (
    ApiTokenMiddleware,
    api_token_configured,
    log_unprotected_api_warning,
    oidc_configured,
)
from replayd.auth.me import build_me_profile
from replayd.auth.oidc import OidcVerifier
from replayd.auth.principal import Principal
from replayd.auth.invitations import (
    create_invitation_for_principal,
    invitation_to_json,
    list_invitations_for_principal,
    list_members_for_principal,
    org_member_to_json,
    revoke_invitation_for_principal,
)
from replayd.auth.incoming_invitations import (
    accept_invitation_for_invitee,
    decline_invitation_for_invitee,
    incoming_invitation_to_json,
    list_incoming_invitations_for_principal,
)
from replayd.auth.members import remove_member_for_principal
from replayd.auth.permissions import CREATE_KEY, REVOKE_KEY, require_permission
from replayd.auth.projects import (
    create_project_for_principal,
    get_project_for_principal,
    list_projects_for_principal,
    project_to_json,
    rename_project_for_principal,
)
from replayd.auth.scoping import (
    exchange_in_read_scope,
    project_id_in_read_scope,
    regression_test_in_read_scope,
    resolve_ingest_key_list_project_ids,
    resolve_list_project_ids_filter,
    resolve_read_scope,
    resolved_project_id,
    run_steps_in_read_scope,
)
from replayd.decoding import decode_body
from replayd.models import Exchange, ProjectIngestKey, RegressionTest, RunSummary, TestResult
from replayd.storage.base import Storage
from replayd.storage.factory import get_storage
from replayd.tenancy import DEFAULT_PROJECT_ID
from replayd.testing import run_regression_test

logger = logging.getLogger(__name__)


class CreateRegressionTestBody(BaseModel):
    name: str
    baseline_run_id: str
    mode: str = "semantic"


class RunRegressionTestBody(BaseModel):
    candidate_run_id: str | None = None


class CreateIngestKeyBody(BaseModel):
    name: str | None = None
    project_id: str | None = None


class CreateProjectBody(BaseModel):
    name: str


class RenameProjectBody(BaseModel):
    name: str


class CreateInvitationBody(BaseModel):
    email: str
    role: str | None = None


def _exchange_to_json(exchange: Exchange) -> dict[str, object]:
    return exchange.model_dump(mode="json")


def _run_summary_to_json(summary: RunSummary) -> dict[str, object]:
    return summary.model_dump(mode="json")


def _regression_test_to_json(test: RegressionTest) -> dict[str, object]:
    return test.model_dump(mode="json")


def _test_result_to_json(result: TestResult) -> dict[str, object]:
    return result.model_dump(mode="json")


def _ingest_key_metadata_to_json(key: ProjectIngestKey) -> dict[str, object]:
    payload = key.model_dump(
        mode="json",
        include={"id", "project_id", "name", "key_prefix", "created_at", "last_used_at"},
    )
    payload["prefix"] = payload.pop("key_prefix")
    payload["revoked"] = key.revoked_at is not None
    return payload


async def _resolve_ingest_key_create_project(
    store: Storage,
    principal: Principal,
    requested_project_id: str | None,
) -> str:
    if requested_project_id is not None:
        project = await get_project_for_principal(store, principal, requested_project_id)
        return project.id

    scope = await resolve_read_scope(store, principal)
    if scope is None:
        return DEFAULT_PROJECT_ID
    if not scope:
        raise HTTPException(status_code=404, detail="project not found")
    if len(scope) == 1:
        return scope[0]
    raise HTTPException(status_code=400, detail="project_id is required")


def _run_parent_run_id(steps: list[Exchange]) -> str | None:
    parent_values = {step.parent_run_id for step in steps}
    return next(iter(parent_values)) if len(parent_values) == 1 else None


def _run_detail_from_steps(run_id: str, steps: list[Exchange]) -> dict[str, object]:
    models = sorted({step.model for step in steps if step.model is not None})
    step_payloads: list[dict[str, object]] = []
    for index, step in enumerate(steps, start=1):
        payload = _exchange_to_json(step)
        payload["step_index"] = index
        step_payloads.append(payload)
    return {
        "run_id": run_id,
        "step_count": len(steps),
        "started_at": min(step.started_at for step in steps),
        "ended_at": max(step.ended_at for step in steps),
        "total_latency_ms": sum(step.latency_ms for step in steps),
        "models": models,
        "final_status": steps[-1].response_status,
        "parent_run_id": _run_parent_run_id(steps),
        "steps": step_payloads,
    }


def _body_response(decoded: bytes) -> Response:
    try:
        json.loads(decoded)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return Response(content=decoded, media_type="text/plain; charset=utf-8")
    return Response(content=decoded, media_type="application/json")


def create_management_app(
    settings: Settings | None = None,
    *,
    storage: Storage | None = None,
    oidc_verifier: OidcVerifier | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    verifier = oidc_verifier or OidcVerifier(resolved_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = resolved_settings
        if api_token_configured(resolved_settings):
            logger.info("control plane API token authentication enabled")
        if oidc_configured(resolved_settings):
            logger.info(
                "control plane OIDC authentication enabled",
                extra={"issuer": resolved_settings.OIDC_ISSUER},
            )
        if not api_token_configured(resolved_settings) and not oidc_configured(
            resolved_settings
        ):
            log_unprotected_api_warning()
        owns_storage = False
        if storage is not None:
            app.state.storage = storage
        else:
            app.state.storage = get_storage(resolved_settings)
            await app.state.storage.init()
            owns_storage = True
            logger.info(
                "management storage ready",
                extra={"storage_dir": resolved_settings.STORAGE_DIR},
            )
        try:
            yield
        finally:
            if owns_storage and app.state.storage is not None:
                await app.state.storage.aclose()

    app = FastAPI(title="replayd-management", lifespan=lifespan)
    app.add_middleware(
        ApiTokenMiddleware,
        settings=resolved_settings,
        verifier=verifier,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[resolved_settings.MGMT_CORS_ORIGIN],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*", "Authorization", "X-Replayd-Token"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "plane": "control"}

    @app.get("/health/oidc")
    async def health_oidc() -> dict[str, object]:
        settings: Settings = app.state.settings
        if not oidc_configured(settings):
            return {"status": "skipped", "detail": "OIDC_ISSUER is not set"}
        try:
            result = await verify_oidc_connectivity(settings)
            return result
        except OidcConnectivityError as exc:
            return JSONResponse(
                status_code=503,
                content={"status": "error", "detail": str(exc)},
            )

    @app.get("/api/me")
    async def get_me(request: Request) -> dict[str, object]:
        store: Storage = request.app.state.storage
        return await build_me_profile(store, request.state.principal)

    @app.get("/api/exchanges")
    async def list_exchanges(
        request: Request,
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        project_id: str | None = Query(default=None),
    ) -> dict[str, object]:
        store: Storage = request.app.state.storage
        scope = await resolve_read_scope(store, request.state.principal)
        project_ids = await resolve_list_project_ids_filter(
            store,
            request.state.principal,
            project_id,
            scope,
        )
        items = await store.list_exchanges(
            limit=limit,
            offset=offset,
            project_ids=project_ids,
        )
        total = await store.count_exchanges(project_ids=project_ids)
        return {
            "items": [_exchange_to_json(item) for item in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @app.get("/api/exchanges/{exchange_id}")
    async def get_exchange(exchange_id: str, request: Request) -> dict[str, object]:
        store: Storage = request.app.state.storage
        exchange = await store.get_exchange(exchange_id)
        if exchange is None:
            raise HTTPException(status_code=404, detail="exchange not found")
        scope = await resolve_read_scope(store, request.state.principal)
        if not exchange_in_read_scope(exchange, scope):
            raise HTTPException(status_code=404, detail="exchange not found")
        return _exchange_to_json(exchange)

    @app.get("/api/exchanges/{exchange_id}/request")
    async def get_exchange_request(exchange_id: str, request: Request) -> Response:
        store: Storage = request.app.state.storage
        exchange = await store.get_exchange(exchange_id)
        if exchange is None or exchange.request_body_hash is None:
            raise HTTPException(status_code=404, detail="exchange request not found")
        scope = await resolve_read_scope(store, request.state.principal)
        if not exchange_in_read_scope(exchange, scope):
            raise HTTPException(status_code=404, detail="exchange request not found")
        raw = await store.get_blob(exchange.request_body_hash)
        decoded = decode_body(raw, exchange.request_headers)
        return _body_response(decoded)

    @app.get("/api/exchanges/{exchange_id}/response")
    async def get_exchange_response(exchange_id: str, request: Request) -> Response:
        store: Storage = request.app.state.storage
        exchange = await store.get_exchange(exchange_id)
        if exchange is None or exchange.response_body_hash is None:
            raise HTTPException(status_code=404, detail="exchange response not found")
        scope = await resolve_read_scope(store, request.state.principal)
        if not exchange_in_read_scope(exchange, scope):
            raise HTTPException(status_code=404, detail="exchange response not found")
        raw = await store.get_blob(exchange.response_body_hash)
        decoded = decode_body(raw, exchange.response_headers)
        return _body_response(decoded)

    @app.get("/api/runs")
    async def list_runs(
        request: Request,
        limit: int = Query(default=50, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        project_id: str | None = Query(default=None),
    ) -> dict[str, object]:
        store: Storage = request.app.state.storage
        scope = await resolve_read_scope(store, request.state.principal)
        project_ids = await resolve_list_project_ids_filter(
            store,
            request.state.principal,
            project_id,
            scope,
        )
        items = await store.list_runs(limit=limit, offset=offset, project_ids=project_ids)
        total = await store.count_runs(project_ids=project_ids)
        return {
            "items": [_run_summary_to_json(item) for item in items],
            "total": total,
        }

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str, request: Request) -> dict[str, object]:
        store: Storage = request.app.state.storage
        steps = await store.get_run(run_id)
        if not steps:
            raise HTTPException(status_code=404, detail="run not found")
        scope = await resolve_read_scope(store, request.state.principal)
        if not run_steps_in_read_scope(steps, scope):
            raise HTTPException(status_code=404, detail="run not found")
        return _run_detail_from_steps(run_id, steps)

    @app.post("/api/tests", status_code=201)
    async def create_test(
        body: CreateRegressionTestBody,
        request: Request,
    ) -> dict[str, object]:
        store: Storage = request.app.state.storage
        baseline_steps = await store.get_run(body.baseline_run_id)
        if not baseline_steps:
            raise HTTPException(status_code=404, detail="baseline run not found")
        scope = await resolve_read_scope(store, request.state.principal)
        if not run_steps_in_read_scope(baseline_steps, scope):
            raise HTTPException(status_code=404, detail="baseline run not found")

        test = RegressionTest(
            id=uuid.uuid4().hex,
            name=body.name,
            baseline_run_id=body.baseline_run_id,
            project_id=resolved_project_id(baseline_steps[0].project_id),
            created_at=datetime.now(UTC),
            mode=body.mode,
        )
        await store.save_test(test)
        return _regression_test_to_json(test)

    @app.get("/api/tests")
    async def list_tests(
        request: Request,
        project_id: str | None = Query(default=None),
    ) -> dict[str, object]:
        store: Storage = request.app.state.storage
        scope = await resolve_read_scope(store, request.state.principal)
        project_ids = await resolve_list_project_ids_filter(
            store,
            request.state.principal,
            project_id,
            scope,
        )
        items = await store.list_tests(project_ids=project_ids)
        return {
            "items": [_regression_test_to_json(item) for item in items],
            "total": len(items),
        }

    @app.get("/api/tests/{test_id}")
    async def get_test(
        test_id: str,
        request: Request,
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, object]:
        store: Storage = request.app.state.storage
        test = await store.get_test(test_id)
        if test is None:
            raise HTTPException(status_code=404, detail="test not found")
        scope = await resolve_read_scope(store, request.state.principal)
        if not regression_test_in_read_scope(test, scope):
            raise HTTPException(status_code=404, detail="test not found")
        results = await store.list_test_results(test_id, limit=limit, offset=offset)
        payload = _regression_test_to_json(test)
        payload["results"] = [_test_result_to_json(result) for result in results]
        return payload

    @app.post("/api/tests/{test_id}/run")
    async def run_test(
        test_id: str,
        request: Request,
        body: RunRegressionTestBody | None = None,
    ) -> dict[str, object]:
        store: Storage = request.app.state.storage
        test = await store.get_test(test_id)
        if test is None:
            raise HTTPException(status_code=404, detail="test not found")
        candidate_run_id = body.candidate_run_id if body is not None else None
        result = await run_regression_test(store, test, candidate_run_id=candidate_run_id)
        return _test_result_to_json(result)

    @app.delete("/api/tests/{test_id}", status_code=204)
    async def delete_test(test_id: str, request: Request) -> Response:
        store: Storage = request.app.state.storage
        deleted = await store.delete_test(test_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="test not found")
        return Response(status_code=204)

    @app.get("/api/projects")
    async def list_projects(request: Request) -> dict[str, object]:
        store: Storage = request.app.state.storage
        items = await list_projects_for_principal(store, request.state.principal)
        return {
            "items": [project_to_json(item) for item in items],
            "total": len(items),
        }

    @app.post("/api/projects", status_code=201)
    async def create_project(
        body: CreateProjectBody,
        request: Request,
    ) -> dict[str, object]:
        store: Storage = request.app.state.storage
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="name is required")
        project = await create_project_for_principal(
            store,
            request.state.principal,
            name=name,
        )
        return project_to_json(project)

    @app.patch("/api/projects/{project_id}")
    async def rename_project(
        project_id: str,
        body: RenameProjectBody,
        request: Request,
    ) -> dict[str, object]:
        store: Storage = request.app.state.storage
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="name is required")
        project = await rename_project_for_principal(
            store,
            request.state.principal,
            project_id,
            name=name,
        )
        return project_to_json(project)

    @app.post("/api/invitations", status_code=201)
    async def create_invitation(
        body: CreateInvitationBody,
        request: Request,
    ) -> dict[str, object]:
        store: Storage = request.app.state.storage
        invitation = await create_invitation_for_principal(
            store,
            request.state.principal,
            email=body.email,
            role=body.role,
        )
        return invitation_to_json(invitation)

    @app.get("/api/invitations")
    async def list_invitations(request: Request) -> dict[str, object]:
        store: Storage = request.app.state.storage
        items = await list_invitations_for_principal(store, request.state.principal)
        return {
            "items": [invitation_to_json(item) for item in items],
            "total": len(items),
        }

    @app.get("/api/invitations/incoming")
    async def list_incoming_invitations(request: Request) -> dict[str, object]:
        store: Storage = request.app.state.storage
        items = await list_incoming_invitations_for_principal(
            store,
            request.state.principal,
        )
        return {
            "items": [incoming_invitation_to_json(item) for item in items],
            "total": len(items),
        }

    @app.post("/api/invitations/{invitation_id}/accept", status_code=204)
    async def accept_invitation_endpoint(
        invitation_id: str,
        request: Request,
    ) -> Response:
        store: Storage = request.app.state.storage
        await accept_invitation_for_invitee(
            store,
            request.state.principal,
            invitation_id,
        )
        return Response(status_code=204)

    @app.post("/api/invitations/{invitation_id}/decline", status_code=204)
    async def decline_invitation_endpoint(
        invitation_id: str,
        request: Request,
    ) -> Response:
        store: Storage = request.app.state.storage
        await decline_invitation_for_invitee(
            store,
            request.state.principal,
            invitation_id,
        )
        return Response(status_code=204)

    @app.delete("/api/invitations/{invitation_id}", status_code=204)
    async def revoke_invitation_endpoint(
        invitation_id: str,
        request: Request,
    ) -> Response:
        store: Storage = request.app.state.storage
        await revoke_invitation_for_principal(
            store,
            request.state.principal,
            invitation_id,
        )
        return Response(status_code=204)

    @app.get("/api/members")
    async def list_members(request: Request) -> dict[str, object]:
        store: Storage = request.app.state.storage
        items = await list_members_for_principal(store, request.state.principal)
        return {
            "items": [org_member_to_json(item) for item in items],
            "total": len(items),
        }

    @app.delete("/api/members/{user_id}", status_code=204)
    async def remove_member(user_id: str, request: Request) -> Response:
        store: Storage = request.app.state.storage
        await remove_member_for_principal(store, request.state.principal, user_id)
        return Response(status_code=204)

    @app.post("/api/ingest-keys", status_code=201)
    async def create_ingest_key(
        body: CreateIngestKeyBody,
        request: Request,
    ) -> dict[str, object]:
        store: Storage = request.app.state.storage
        project_id = await _resolve_ingest_key_create_project(
            store,
            request.state.principal,
            body.project_id,
        )
        project = await store.get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        await require_permission(
            store,
            request.state.principal,
            project.org_id,
            CREATE_KEY,
        )
        key_model, plaintext = await store.create_ingest_key(project_id, body.name)
        payload = _ingest_key_metadata_to_json(key_model)
        payload["token"] = plaintext
        return payload

    @app.get("/api/ingest-keys")
    async def list_ingest_keys(
        request: Request,
        project_id: str | None = Query(default=None),
    ) -> dict[str, object]:
        store: Storage = request.app.state.storage
        default_project_ids = await resolve_ingest_key_list_project_ids(
            store,
            request.state.principal,
        )
        project_ids = await resolve_list_project_ids_filter(
            store,
            request.state.principal,
            project_id,
            default_project_ids,
        )
        items = await store.list_ingest_keys_for_projects(project_ids)
        return {
            "items": [_ingest_key_metadata_to_json(item) for item in items],
            "total": len(items),
        }

    @app.delete("/api/ingest-keys/{key_id}", status_code=204)
    async def revoke_ingest_key_endpoint(key_id: str, request: Request) -> Response:
        store: Storage = request.app.state.storage
        key = await store.get_ingest_key(key_id)
        if key is None:
            raise HTTPException(status_code=404, detail="ingest key not found")
        scope = await resolve_read_scope(store, request.state.principal)
        if not project_id_in_read_scope(key.project_id, scope):
            raise HTTPException(status_code=404, detail="ingest key not found")
        project = await store.get_project(key.project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="ingest key not found")
        await require_permission(
            store,
            request.state.principal,
            project.org_id,
            REVOKE_KEY,
        )
        await store.revoke_ingest_key(key_id)
        return Response(status_code=204)

    return app


app = create_management_app()
