"""FastAPI application entry point.

Phase 0: app skeleton with health check + CORS + logging. Domain routers
land in Phase 1+.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.deps import authentication_required, resolve_user_id
from app.core.exception_handlers import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal  # noqa: F401  (ensures engine is created at import)


logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    logger.info(
        "app.startup",
        env=settings.app_env,
        host=settings.app_host,
        port=settings.app_port,
    )
    yield
    logger.info("app.shutdown")


app = FastAPI(
    title="GapMind API",
    description="Evidence-grounded, Human-in-the-Loop AI Research Workspace",
    version="0.1.0",
    lifespan=lifespan,
)

register_exception_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Accept", "Authorization", "Content-Type", "X-User-ID"],
    expose_headers=["X-File-Name"],
)


@app.middleware("http")
async def enforce_delivery_access(request: Request, call_next):
    """Require delivery auth and workspace ownership outside development.

    This is intentionally a small deployment guard for the competition
    package.  It is not intended to replace an institutional identity
    provider, group membership service, or a full RBAC implementation.
    """
    path = request.url.path
    if not path.startswith("/api/v1") or path.startswith("/api/v1/health"):
        return await call_next(request)

    try:
        user_id = resolve_user_id(
            authorization=request.headers.get("Authorization"),
            x_user_id=request.headers.get("X-User-ID"),
        )
    except HTTPException as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )

    if authentication_required():
        parts = path.removeprefix("/api/v1/").split("/")
        if len(parts) >= 2 and parts[0] == "workspaces":
            workspace_id = parts[1]
            if workspace_id != "independent":
                from app.db.session import SessionLocal
                from app.domains.workspace.models import Workspace

                try:
                    with SessionLocal() as db:
                        workspace = db.scalar(
                            select(Workspace).where(
                                Workspace.id == workspace_id,
                                Workspace.is_deleted.is_(False),
                                Workspace.owner_id == user_id,
                            )
                        )
                except Exception:
                    return JSONResponse(
                        status_code=503,
                        content={
                            "detail": {
                                "error": "workspace_acl_unavailable",
                                "message": "Workspace access check is temporarily unavailable",
                                "retryable": True,
                            }
                        },
                    )
                if workspace is None:
                    return JSONResponse(
                        status_code=404,
                        content={
                            "detail": {
                                "error": "workspace_not_found",
                                "message": "Workspace not found",
                                "retryable": False,
                            }
                        },
                    )

    request.state.user_id = user_id
    return await call_next(request)

app.include_router(api_router)


@app.get("/")
def root() -> dict[str, str]:
    """Root redirect hint - real API lives under /api/v1."""
    return {"name": "GapMind API", "docs": "/docs", "openapi": "/openapi.json"}
