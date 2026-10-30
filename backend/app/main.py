"""FastAPI application factory and application entry point."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes.system import router as system_router
from app.api.routes.auth import router as auth_router
from app.api.routes.catalog import router as catalog_router
from app.api.routes.operations import router as operations_router
from app.api.routes.rag import router as rag_router
from app.api.routes.agents import router as agents_router
from app.api.routes.reports import router as reports_router
from app.api.routes.imports import router as imports_router
from app.api.routes.observability import router as observability_router
from app.config import Settings, get_settings
from app.errors import AppError, app_error_handler, http_error_handler, unhandled_error_handler, validation_error_handler
from app.logging_config import configure_logging
from app.middleware import request_context_middleware


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()
    configure_logging(active_settings.log_level)
    application = FastAPI(
        title="ChargeOps API",
        version=active_settings.app_version,
        description="ChargeOps 充电站选址与扩容决策平台基础 API",
    )
    application.state.settings = active_settings
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(active_settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Trace-ID"],
    )
    application.middleware("http")(request_context_middleware)
    application.add_exception_handler(AppError, app_error_handler)
    application.add_exception_handler(RequestValidationError, validation_error_handler)
    application.add_exception_handler(StarletteHTTPException, http_error_handler)
    application.add_exception_handler(Exception, unhandled_error_handler)
    application.include_router(system_router)
    application.include_router(auth_router)
    application.include_router(catalog_router)
    application.include_router(operations_router)
    application.include_router(rag_router)
    application.include_router(agents_router)
    application.include_router(reports_router)
    application.include_router(imports_router)
    application.include_router(observability_router)

    @application.middleware("http")
    async def inject_settings(request: Request, call_next):
        request.state.settings = active_settings
        return await call_next(request)

    return application


app = create_app()
