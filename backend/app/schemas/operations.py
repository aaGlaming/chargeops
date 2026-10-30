from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.catalog import RegionSummary, SourceInfo, StationListItem


class MetricItem(BaseModel):
    id: int
    station_id: int
    metric_date: date
    metric_hour: int | None = Field(default=None, ge=0, le=23)
    timezone: str
    charging_sessions: int | None = None
    energy_kwh: float | None = None
    peak_power_kw: float | None = None
    occupancy_rate: float | None = None
    avg_session_minutes: float | None = None
    data_as_of: date | None = None
    source: SourceInfo


class MetricListResponse(BaseModel):
    items: list[MetricItem]
    page: dict[str, int | bool]


class MetricQuery(BaseModel):
    station_id: int | None = Field(default=None, ge=1)
    start_date: date | None = None
    end_date: date | None = None
    metric_hour: int | None = Field(default=None, ge=0, le=23)
    source_type: Literal["public", "user_upload", "synthetic", "agent"] | None = None
    data_version: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=500)


class FaultItem(BaseModel):
    id: int
    station_id: int
    external_fault_id: str | None = None
    fault_type: str
    severity: str
    started_at: datetime
    recovered_at: datetime | None = None
    affected_connectors: int | None = None
    root_cause: str | None = None
    status: str
    data_as_of: date | None = None
    source: SourceInfo


class FaultListResponse(BaseModel):
    items: list[FaultItem]
    page: dict[str, int | bool]


class FaultQuery(BaseModel):
    station_id: int | None = Field(default=None, ge=1)
    status: str | None = None
    severity: str | None = None
    started_from: datetime | None = None
    started_to: datetime | None = None
    source_type: Literal["public", "user_upload", "synthetic", "agent"] | None = None
    data_version: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=500)


class FaultCreate(BaseModel):
    external_fault_id: str | None = Field(default=None, max_length=128)
    fault_type: str = Field(min_length=1, max_length=64)
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    started_at: datetime
    recovered_at: datetime | None = None
    affected_connectors: int | None = Field(default=None, ge=0)
    root_cause: str | None = Field(default=None, max_length=255)
    data_as_of: date | None = None
    source_type: Literal["public", "user_upload", "synthetic", "agent"] = "user_upload"
    source_url: str | None = None
    source_file: str | None = None
    data_version: str | None = None


class FaultUpdate(BaseModel):
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] | None = None
    recovered_at: datetime | None = None
    affected_connectors: int | None = Field(default=None, ge=0)
    root_cause: str | None = Field(default=None, max_length=255)
    status: Literal["OPEN", "RECOVERED", "CLOSED"] | None = None


class CompletenessInfo(BaseModel):
    score: float
    missing_fields: list[str] = Field(default_factory=list)
    evaluable: bool
    recommendable: bool


class FreshnessInfo(BaseModel):
    data_as_of: date | None = None
    age_days: int | None = None
    status: Literal["CURRENT", "STALE", "UNKNOWN"]


class CandidateWrite(BaseModel):
    external_candidate_id: str | None = Field(default=None, max_length=128)
    site_name: str | None = Field(default=None, min_length=1, max_length=500)
    region_id: int | None = Field(default=None, ge=1)
    region_code: str | None = Field(default=None, max_length=32)
    city: str | None = None
    state: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    area_sqm: float | None = Field(default=None, ge=0)
    parking_spaces: int | None = Field(default=None, ge=0)
    electric_capacity_kw: float | None = Field(default=None, ge=0)
    budget_usd: float | None = Field(default=None, ge=0)
    traffic_index: float | None = Field(default=None, ge=0)
    population_density: float | None = Field(default=None, ge=0)
    planned_open_date: date | None = None
    data_as_of: date | None = None
    lifecycle_status: Literal["DRAFT", "REVIEW", "RECOMMENDED", "ARCHIVED"] = "DRAFT"
    source_type: Literal["public", "user_upload", "synthetic", "agent"] = "user_upload"
    source_url: str | None = None
    source_file: str | None = None
    data_version: str | None = None


class CandidateStatusUpdate(BaseModel):
    lifecycle_status: Literal["DRAFT", "REVIEW", "RECOMMENDED", "ARCHIVED"]
    reason: str | None = Field(default=None, max_length=1000)


class CandidateItem(BaseModel):
    id: int
    external_candidate_id: str
    site_name: str
    region: RegionSummary | None = None
    city: str | None = None
    state: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    area_sqm: float | None = None
    parking_spaces: int | None = None
    electric_capacity_kw: float | None = None
    budget_usd: float | None = None
    traffic_index: float | None = None
    population_density: float | None = None
    planned_open_date: date | None = None
    data_as_of: date | None = None
    data_status: str
    lifecycle_status: str
    completeness: CompletenessInfo
    freshness: FreshnessInfo
    source: SourceInfo


class CandidateDetail(CandidateItem):
    nearby_stations: list[StationListItem] = Field(default_factory=list)
    policies: list[dict[str, object]] = Field(default_factory=list)
    related: dict[str, int | str] = Field(default_factory=dict)


class CandidateListResponse(BaseModel):
    items: list[CandidateItem]
    page: dict[str, int | bool]
