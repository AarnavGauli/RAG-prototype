"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.api import conversations, documents, evaluation, health
from app.config import Settings
from app.context import AppContext, build_context
from app.errors import AppError, error_body
from app.migrations import upgrade_to_head
from app.security import BodyLimitMiddleware, RateLimiter, SecurityHeadersMiddleware
from app.services import indexing

log = logging.getLogger("pdfi")


def _warm_up(ctx: AppContext) -> None:
    try:
        ctx.embedder.check_ready()
    except Exception as exc:
        log.warning("Embedding provider not ready: %s", getattr(exc, "message", type(exc).__name__))


def create_app(settings: Settings | None = None, *, ctx: AppContext | None = None, migrate: bool = True) -> FastAPI:
    settings = settings or (ctx.settings if ctx else Settings())
    logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpcore", "huggingface_hub"):  # their INFO logs include full request URLs
        logging.getLogger(noisy).setLevel(logging.WARNING)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app_ctx = ctx or build_context(settings)
        if migrate:
            upgrade_to_head(settings.database_url or "")
        else:
            from app.db import Base

            Base.metadata.create_all(app_ctx.engine)
        app.state.ctx = app_ctx
        app.state.limiter = RateLimiter(settings.rate_limit_per_minute)
        indexing.recover_on_startup(app_ctx)
        app_ctx.executor.submit(_warm_up, app_ctx)  # loads/downloads the local embedding model early
        yield
        app_ctx.close()

    app = FastAPI(
        title="PDF Intelligence API",
        version=__version__,
        description="Upload PDFs, ask questions, get answers with validated page-level citations.",
        lifespan=lifespan,
    )
    # Middleware order: last added runs first.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )
    app.add_middleware(
        BodyLimitMiddleware, upload_limit=settings.max_upload_bytes, json_limit=settings.max_json_body_kb * 1024
    )
    app.add_middleware(SecurityHeadersMiddleware)

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        headers = (
            {"Retry-After": str(exc.details["retry_after"])} if exc.details and "retry_after" in exc.details else None
        )
        return JSONResponse(
            error_body(exc.code, exc.message, exc.details), status_code=exc.status_code, headers=headers
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
        first = errors[0]["message"] if errors else "Invalid request."
        return JSONResponse(error_body("validation_error", first, {"errors": errors}), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(error_body(code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.error("Unhandled error: %s", type(exc).__name__, exc_info=exc)
        return JSONResponse(error_body("internal_error", "An unexpected error occurred."), status_code=500)

    prefix = "/api/v1"
    for r in (health.router, documents.router, conversations.router, evaluation.router):
        app.include_router(r, prefix=prefix)
    return app


def app_factory() -> FastAPI:  # for `uvicorn app.main:app_factory --factory`
    return create_app()
