"""Request/trace IDs and structured access logs."""

from __future__ import annotations

import logging
import time
from uuid import uuid4

from fastapi import Request

from app.context import request_id_var, trace_id_var, user_id_var
from app.telemetry import record_sample


logger = logging.getLogger("chargeops.access")


async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    trace_id = request.headers.get("X-Trace-ID") or request_id
    request.state.request_id = request_id
    request.state.trace_id = trace_id
    request_token = request_id_var.set(request_id)
    trace_token = trace_id_var.set(trace_id)
    user_token = user_id_var.set(None)
    started = time.perf_counter()
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Trace-ID"] = trace_id
        status = "error" if response.status_code >= 500 else "success"
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        record_sample("http_request", duration_ms, status)
        logger.info(
            "request completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response
    finally:
        request_id_var.reset(request_token)
        trace_id_var.reset(trace_token)
        user_id_var.reset(user_token)
