from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    trace_id: str


class DependencyCheck(BaseModel):
    service: str
    status: str
    detail: str
    retryable: bool = False


class ReadyResponse(BaseModel):
    status: str
    ready: bool
    checks: list[DependencyCheck] = Field(default_factory=list)
    trace_id: str
    config: dict[str, Any] | None = None
