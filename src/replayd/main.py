import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI, Request
from starlette.responses import Response

from replayd import __version__
from replayd.config import Settings, get_settings
from replayd.proxy import (
    PROXY_METHODS,
    branch_request,
    forward_request,
    replay_request,
    resolve_branch_parent_run_id,
    resolve_candidate_run_id,
    resolve_replay_run_id,
    resolve_run_id_from_request,
)
from replayd.storage.base import Storage
from replayd.storage.factory import get_storage

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    http_client: httpx.AsyncClient | None = None,
    storage: Storage | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = resolved_settings
        owns_storage = False
        if storage is not None:
            app.state.storage = storage
        elif resolved_settings.CAPTURE_ENABLED:
            app.state.storage = get_storage(resolved_settings)
            await app.state.storage.init()
            owns_storage = True
            logger.info(
                "capture storage ready",
                extra={"storage_dir": resolved_settings.STORAGE_DIR},
            )
        else:
            app.state.storage = None

        if http_client is not None:
            app.state.http_client = http_client
            logger.info("proxy client ready (injected)")
            try:
                yield
            finally:
                if owns_storage and app.state.storage is not None:
                    await app.state.storage.aclose()
            return

        async with httpx.AsyncClient(
            base_url=resolved_settings.UPSTREAM_BASE_URL,
            follow_redirects=False,
        ) as client:
            app.state.http_client = client
            logger.info(
                "proxy client ready",
                extra={"upstream_base_url": resolved_settings.UPSTREAM_BASE_URL},
            )
            try:
                yield
            finally:
                if owns_storage and app.state.storage is not None:
                    await app.state.storage.aclose()

    app = FastAPI(title="Replayd", version=__version__, lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        logger.info("health check requested")
        return {"status": "ok", "version": __version__}

    @app.api_route("/{full_path:path}", methods=PROXY_METHODS)
    async def proxy(full_path: str, request: Request) -> Response:
        del full_path
        settings = request.app.state.settings
        branch_parent_run_id = resolve_branch_parent_run_id(request, settings)
        replay_run_id = resolve_replay_run_id(request, settings)
        branch_run_id = (
            resolve_run_id_from_request(request, settings)
            if branch_parent_run_id is not None
            else None
        )

        if branch_parent_run_id is not None:
            logger.info(
                "proxy dispatch",
                extra={
                    "mode": "branch",
                    "parent_run_id": branch_parent_run_id,
                    "branch_run_id": branch_run_id,
                    "method": request.method,
                    "path": request.url.path,
                },
            )
            return await branch_request(
                request,
                request.app.state.http_client,
                request.app.state.storage,
                settings,
            )

        if replay_run_id is not None:
            logger.info(
                "proxy dispatch",
                extra={
                    "mode": "replay",
                    "replay_run_id": replay_run_id,
                    "candidate_run_id": resolve_candidate_run_id(request, settings),
                    "method": request.method,
                    "path": request.url.path,
                },
            )
            return await replay_request(
                request,
                request.app.state.storage,
                settings,
            )

        logger.info(
            "proxy dispatch",
            extra={
                "mode": "forward",
                "method": request.method,
                "path": request.url.path,
            },
        )
        capture_storage = None
        if settings.CAPTURE_ENABLED:
            capture_storage = request.app.state.storage
        return await forward_request(
            request,
            request.app.state.http_client,
            storage=request.app.state.storage,
            capture=settings.CAPTURE_ENABLED,
            settings=settings,
        )

    return app


app = create_app()


def run() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    uvicorn.run(
        "replayd.main:app",
        host=settings.LISTEN_HOST,
        port=settings.LISTEN_PORT,
        reload=False,
    )


if __name__ == "__main__":
    run()
