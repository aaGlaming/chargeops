from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


ReportStatus = Literal["DRAFT", "WAITING_CONFIRMATION", "APPROVED", "REJECTED", "ARCHIVED"]
ReportDecision = Literal["APPROVE", "REJECT"]


class ReportCreateRequest(BaseModel):
    run_id: str = Field(min_length=36, max_length=36)
    title: str | None = Field(default=None, max_length=500)


class ReportConfirmationRequest(BaseModel):
    decision: ReportDecision
    comment: str = Field(min_length=1, max_length=2000)


class ReportSummary(BaseModel):
    report_id: str
    run_id: str
    report_type: str
    title: str
    status: ReportStatus
    data_version: str | None = None
    calculation_rule_version: str | None = None
    confirmed_by: int | None = None
    confirmed_at: datetime | None = None
    created_by: int
    created_at: datetime
    updated_at: datetime


class ReportDetail(ReportSummary):
    conclusion: str | None = None
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    calculation_summary: dict[str, Any] = Field(default_factory=dict)
    business_data: dict[str, Any] = Field(default_factory=dict)
    rag_evidence: list[dict[str, Any]] = Field(default_factory=list)
    prompt_version: str | None = None
    model_version: str | None = None
    embedding_model: str | None = None
    data_batch_ids: list[int] = Field(default_factory=list)
    document_versions: list[str] = Field(default_factory=list)
    confirmation_type: str | None = None
    confirmation_comment: str | None = None
    rejection_reason: str | None = None
    archived_at: datetime | None = None


class ReportListResponse(BaseModel):
    items: list[ReportSummary]
