"""Unified API errors and exception handlers."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.context import current_trace_id


logger = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(self, error_code: str, message: str, status_code: int = 400, retryable: bool = False, details: Any = None, headers: dict[str, str] | None = None):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.details = details
        self.headers = headers or {}


def error_payload(error_code: str, message: str, retryable: bool, details: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "error_code": error_code,
        "message": message,
        "trace_id": current_trace_id(),
        "retryable": retryable,
    }
    if details is not None:
        payload["details"] = details
    return payload


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(content=error_payload(exc.error_code, exc.message, exc.retryable, exc.details), status_code=exc.status_code, headers=exc.headers)


async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return JSONResponse(content=error_payload(f"HTTP_{exc.status_code}", detail, exc.status_code >= 500), status_code=exc.status_code)


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = [{"location": list(error.get("loc", [])), "message": error.get("msg", "Invalid value")} for error in exc.errors()]
    return JSONResponse(content=error_payload("VALIDATION_ERROR", "Request validation failed", False, details), status_code=422)


async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled application exception", exc_info=exc)
    return JSONResponse(content=error_payload("INTERNAL_SERVER_ERROR", "Internal server error", True), status_code=500)
