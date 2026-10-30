from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.agents.contracts import AgentStatus, AgentType, StopReason, ToolContract


class AgentRunCreateRequest(BaseModel):
    agent_type: AgentType
    input_payload: dict[str, Any] = Field(default_factory=dict)
    business_scope: dict[str, Any] = Field(default_factory=dict)
    data_version: str | None = Field(default=None, max_length=64)
    prompt_version: str = Field(default="agent-contract-v1", max_length=64)
    model_name: str | None = Field(default=None, max_length=255)
    embedding_model: str | None = Field(default=None, max_length=255)


class AgentRunTransitionRequest(BaseModel):
    status: AgentStatus
    current_stage: str = Field(default="UPDATED", max_length=128)
    stop_reason: StopReason | None = None
    confirmation_status: str = Field(default="NOT_REQUIRED", max_length=32)
    state_patch: dict[str, Any] = Field(default_factory=dict)


class AgentRunSummary(BaseModel):
    run_id: str
    agent_type: str
    requested_by: int
    status: str
    data_version: str | None = None
    prompt_version: str | None = None
    model_name: str | None = None
    embedding_model: str | None = None
    stop_reason: str | None = None
    confirmation_status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ToolCallRecordResponse(BaseModel):
    id: int
    run_id: str
    sequence_no: int
    tool_name: str
    permission_code: str | None = None
    risk_level: str
    idempotency_key: str | None = None
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    status: str
    error_code: str | None = None
    retryable: bool
    duration_ms: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AgentRunEventResponse(BaseModel):
    id: int
    run_id: str
    sequence_no: int
    event_type: str
    status: str
    provider: str | None = None
    model_name: str | None = None
    confirmation_type: str | None = None
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    retryable: bool
    duration_ms: int | None = None
    actor_user_id: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AgentRunDetail(AgentRunSummary):
    input_payload: dict[str, Any] = Field(default_factory=dict)
    business_scope: dict[str, Any] = Field(default_factory=dict)
    evidence_summary: dict[str, Any] = Field(default_factory=dict)
    state_snapshot: dict[str, Any] = Field(default_factory=dict)
    tool_calls: list[ToolCallRecordResponse] = Field(default_factory=list)
    events: list[AgentRunEventResponse] = Field(default_factory=list)


class AgentRunListResponse(BaseModel):
    items: list[AgentRunSummary]


class AgentContractListResponse(BaseModel):
    items: list[ToolContract]


class ToolExecuteRequest(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=255)


class ToolExecuteResponse(BaseModel):
    run_id: str
    tool_name: str
    tool_call_id: int
    status: str
    result: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None
    duration_ms: int | None = None
