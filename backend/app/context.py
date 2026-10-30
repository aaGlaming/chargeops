"""Request and trace context variables used by logs and responses."""

from __future__ import annotations

from contextvars import ContextVar


request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")
user_id_var: ContextVar[int | None] = ContextVar("user_id", default=None)


def current_request_id() -> str:
    return request_id_var.get()


def current_trace_id() -> str:
    return trace_id_var.get()


def current_user_id() -> int | None:
    return user_id_var.get()
