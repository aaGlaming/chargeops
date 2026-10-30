from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AuditLogItem(BaseModel):
    id: int
    occurred_at: datetime
    actor_user_id: int | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    request_id: str | None = None
    trace_id: str | None = None
    agent_run_id: str | None = None
    tool_call_id: int | None = None
    import_batch_id: int | None = None
    severity: str
    before_state: dict[str, Any] | None = None
    after_state: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class AuditLogListResponse(BaseModel):
    items: list[AuditLogItem]
    page: dict[str, int | bool]


class MonitoringComponent(BaseModel):
    count: int
    error_count: int
    p95_latency_ms: float


class MonitoringOverview(BaseModel):
    generated_at: datetime
    readiness: dict[str, Any]
    telemetry: dict[str, Any]
    database: dict[str, Any]
    disk: dict[str, Any]
    models: dict[str, Any]
    agent_runs: dict[str, int]
    imports: dict[str, int]
    audit: dict[str, int]
    components: dict[str, MonitoringComponent] = Field(default_factory=dict)


class AlertState(BaseModel):
    code: str
    label: str
    severity: str
    enabled: bool
    current_status: str
    detail: str


class AlertListResponse(BaseModel):
    items: list[AlertState]
