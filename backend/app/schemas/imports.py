from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


DatasetType = Literal["stations", "connectors", "metrics", "faults", "candidates", "expansion"]


class ImportFieldDefinition(BaseModel):
    key: str
    label: str
    kind: Literal["text", "number", "date", "datetime"]
    required: bool = False
    hint: str


class ImportValidationError(BaseModel):
    row: int
    field: str
    level: Literal["error", "warning"]
    message: str
    suggestion: str


class ImportPreviewResponse(BaseModel):
    dataset_type: DatasetType
    file_name: str
    headers: list[str]
    rows: list[dict[str, str]]
    mapping: dict[str, str]
    fields: list[ImportFieldDefinition]
    errors: list[ImportValidationError]
    total_rows: int


class ImportConfirmRequest(BaseModel):
    dataset_type: DatasetType
    file_name: str = Field(min_length=1, max_length=500)
    data_version: str = Field(min_length=1, max_length=64)
    mapping: dict[str, str] = Field(default_factory=dict)
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=100000)


class ImportBatchSummary(BaseModel):
    id: int
    batch_key: str
    dataset_type: str
    source_type: str
    source_file: str | None = None
    source_sha256: str | None = None
    data_version: str
    row_count: int
    success_count: int
    failed_count: int
    skipped_count: int
    status: str
    rollback_status: str
    created_at: datetime
    completed_at: datetime | None = None


class ImportBatchDetail(ImportBatchSummary):
    errors: list[dict[str, Any]] = Field(default_factory=list)


class ImportBatchListResponse(BaseModel):
    items: list[ImportBatchSummary]
    page: dict[str, int | bool]

