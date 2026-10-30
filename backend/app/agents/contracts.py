"""Stable Agent graph state, business schemas and execution contracts."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field


AgentType = Literal["coverage_gap", "competition", "site_selection", "expansion", "policy_matching"]
AgentStatus = Literal["PENDING", "RUNNING", "WAITING_CONFIRMATION", "COMPLETED", "FAILED", "BLOCKED", "CANCELLED"]
ConfirmationStatus = Literal["NOT_REQUIRED", "PENDING", "APPROVED", "REJECTED"]
StopReason = Literal[
    "EVIDENCE_INSUFFICIENT",
    "MISSING_BUSINESS_DATA",
    "STALE_DATA",
    "WAITING_CONFIRMATION",
    "MODEL_ERROR",
    "TOOL_ERROR",
    "TIMEOUT",
    "CANCELLED",
    "NO_PROGRESS",
]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH"]

AGENT_TYPES: tuple[str, ...] = ("coverage_gap", "competition", "site_selection", "expansion", "policy_matching")
STOP_REASONS: tuple[str, ...] = (
    "EVIDENCE_INSUFFICIENT", "MISSING_BUSINESS_DATA", "STALE_DATA", "WAITING_CONFIRMATION",
    "MODEL_ERROR", "TOOL_ERROR", "TIMEOUT", "CANCELLED", "NO_PROGRESS",
)


class AgentEvidence(BaseModel):
    evidence_id: str
    document_id: int | None = None
    chunk_id: str | None = None
    title: str | None = None
    content: str
    source_url: str | None = None
    original_fragment: str | None = None
    original_href: str | None = None
    version: str | None = None
    start_char: int | None = None
    end_char: int | None = None
    score: float | None = None


class AgentError(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime | None = None


class AgentInputBase(BaseModel):
    data_version: str | None = Field(default=None, max_length=64)
    prompt_version: str = Field(default="agent-contract-v1", max_length=64)
    business_scope: dict[str, Any] = Field(default_factory=dict)


class CoverageGapInput(AgentInputBase):
    prompt_version: str = Field(default="coverage-gap-v1", max_length=64)
    region_code: str = Field(min_length=1, max_length=32)
    charger_type: Literal["ALL", "FAST", "SLOW"] = "ALL"
    coverage_radius_km: float = Field(default=5.0, gt=0, le=100)
    threshold: float = Field(default=0.8, ge=0, le=1)
    fast_ratio_threshold: float = Field(default=0.3, ge=0, le=1)
    time_gap_occupancy_threshold: float = Field(default=0.85, ge=0, le=1)
    stale_after_days: int = Field(default=365, ge=1, le=3650)
    analysis_date: date | None = None


class CompetitionInput(AgentInputBase):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_km: float = Field(default=5.0, gt=0, le=100)
    operator_code: str | None = Field(default=None, max_length=64)


class SiteSelectionInput(AgentInputBase):
    candidate_site_ids: list[int] = Field(min_length=1, max_length=100)
    weights: dict[str, float] = Field(default_factory=dict)
    target_score: float = Field(default=70, ge=0, le=100)


class ExpansionInput(AgentInputBase):
    station_ids: list[int] = Field(min_length=1, max_length=100)
    start_date: date | None = None
    end_date: date | None = None
    budget_usd: float | None = Field(default=None, ge=0)


class PolicyMatchingInput(AgentInputBase):
    region_code: str = Field(min_length=1, max_length=32)
    subject_type: str = Field(min_length=1, max_length=64)
    planned_scale_kw: float | None = Field(default=None, ge=0)
    planned_date: date | None = None


class AgentOutputBase(BaseModel):
    status: Literal["COMPLETED", "WAITING_CONFIRMATION", "EVIDENCE_INSUFFICIENT", "MISSING_BUSINESS_DATA", "STALE_DATA", "FAILED"]
    conclusion: str | None = None
    stop_reason: StopReason | None = None
    evidence: list[AgentEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    data_version: str | None = None


class CoverageGapOutput(AgentOutputBase):
    coverage_score: float | None = None
    gap_types: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    data_insufficiency: list[str] = Field(default_factory=list)
    nearest_station_distance_km: float | None = None
    station_density_per_sq_km: float | None = None
    temporal_gap: dict[str, Any] = Field(default_factory=dict)
    freshness: dict[str, Any] = Field(default_factory=dict)


class CompetitionOutput(AgentOutputBase):
    competition_index: float | None = None
    nearby_stations: list[dict[str, Any]] = Field(default_factory=list)
    operator_distribution: dict[str, int] = Field(default_factory=dict)


class SiteSelectionOutput(AgentOutputBase):
    ranked_candidates: list[dict[str, Any]] = Field(default_factory=list)
    selected_candidate_id: int | None = None
    scoring_breakdown: dict[str, Any] = Field(default_factory=dict)


class ExpansionOutput(AgentOutputBase):
    plans: list[dict[str, Any]] = Field(default_factory=list)
    confirmation_status: ConfirmationStatus = "NOT_REQUIRED"
    risk_summary: list[str] = Field(default_factory=list)


class PolicyMatchingOutput(AgentOutputBase):
    matched_policies: list[dict[str, Any]] = Field(default_factory=list)
    missing_conditions: list[str] = Field(default_factory=list)
    required_materials: list[str] = Field(default_factory=list)


class AgentGraphState(TypedDict, total=False):
    run_id: str
    agent_type: AgentType
    user_input: dict[str, Any]
    business_scope: dict[str, Any]
    data_version: str | None
    prompt_version: str | None
    model_name: str | None
    embedding_model: str | None
    retrieval_queries: list[dict[str, Any]]
    evidence: list[AgentEvidence]
    tool_results: dict[str, Any]
    calculation_results: dict[str, Any]
    conclusion: dict[str, Any] | None
    errors: list[AgentError]
    stop_reason: StopReason | None
    status: AgentStatus
    current_stage: str
    resume_stage: str | None
    retry_counts: dict[str, int]
    progress_signature: str | None
    no_progress_streak: int
    confirmation_status: ConfirmationStatus
    iteration: int
    tool_call_count: int
    model_call_count: int
    state_version: int


class AgentStateSnapshot(BaseModel):
    run_id: str
    agent_type: AgentType
    user_input: dict[str, Any] = Field(default_factory=dict)
    business_scope: dict[str, Any] = Field(default_factory=dict)
    data_version: str | None = None
    prompt_version: str | None = None
    model_name: str | None = None
    embedding_model: str | None = None
    retrieval_queries: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[AgentEvidence] = Field(default_factory=list)
    tool_results: dict[str, Any] = Field(default_factory=dict)
    calculation_results: dict[str, Any] = Field(default_factory=dict)
    conclusion: dict[str, Any] | None = None
    errors: list[AgentError] = Field(default_factory=list)
    stop_reason: StopReason | None = None
    status: AgentStatus = "PENDING"
    current_stage: str = "CREATED"
    resume_stage: str | None = None
    retry_counts: dict[str, int] = Field(default_factory=dict)
    progress_signature: str | None = None
    no_progress_streak: int = 0
    confirmation_status: ConfirmationStatus = "NOT_REQUIRED"
    iteration: int = 0
    tool_call_count: int = 0
    model_call_count: int = 0
    state_version: int = 1


class ToolContract(BaseModel):
    name: str
    category: Literal["mysql_query", "deterministic_calculation", "rag_search", "result_write"]
    description: str
    permission_code: str
    input_schema: str
    output_schema: str
    risk_level: RiskLevel = "LOW"
    idempotency_required: bool = False
    retryable_error_codes: list[str] = Field(default_factory=list)
    allowed_agent_types: list[AgentType] = Field(default_factory=list)
    requires_confirmation: bool = False
    confirmation_type: str | None = None


class ModelCallRecord(BaseModel):
    run_id: str
    sequence_no: int
    provider: str
    model_name: str
    prompt_version: str | None = None
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    status: Literal["PENDING", "SUCCEEDED", "FAILED"] = "PENDING"
    error_code: str | None = None
    retryable: bool = False
    duration_ms: int | None = None


class ConfirmationRecord(BaseModel):
    run_id: str
    confirmation_type: str
    status: ConfirmationStatus
    requested_by: int | None = None
    decided_by: int | None = None
    comment: str | None = None
    requested_at: datetime | None = None
    decided_at: datetime | None = None
