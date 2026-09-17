"""FastAPI entrypoint (A-TO-Z-PLAN.md §Phase 1). Phase 0: /v1 prefix, health, OpenAPI,
request-id + correlation-id middleware, error envelope. Auth + tenant middleware land in Phase 1."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from common.logging import configure_logging, get_logger
from common.settings import settings

configure_logging()
log = get_logger("api")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    log.info("api.start", env=settings.env)
    yield
    log.info("api.stop")


app = FastAPI(
    title="autonomous-seo-agent API",
    version="0.1.0",
    lifespan=lifespan,
    openapi_url="/v1/openapi.json",
)


@app.middleware("http")
async def correlation_id(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    cid = request.headers.get("x-correlation-id") or str(uuid.uuid4())
    rid = str(uuid.uuid4())
    structlog.contextvars.bind_contextvars(correlation_id=cid, request_id=rid)
    try:
        response = await call_next(request)
    except Exception:  # noqa: BLE001 - top-level envelope
        log.exception("api.unhandled", path=request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "Internal server error"}},
            headers={"x-request-id": rid, "x-correlation-id": cid},
        )
    finally:
        structlog.contextvars.clear_contextvars()
    response.headers["x-request-id"] = rid
    response.headers["x-correlation-id"] = cid
    return response


from app.routers import data, health, oauth, opportunities, projects, websites  # noqa: E402

app.include_router(health.router, prefix="/v1")
app.include_router(projects.router, prefix="/v1")
app.include_router(websites.router, prefix="/v1")
app.include_router(opportunities.router, prefix="/v1")
app.include_router(data.router, prefix="/v1")
app.include_router(oauth.router, prefix="/v1")
