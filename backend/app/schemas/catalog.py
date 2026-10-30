from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SourceInfo(BaseModel):
    source_type: str
    source_url: str | None = None
    source_file: str | None = None
    data_version: str
    import_batch_id: int | None = None


class RegionSummary(BaseModel):
    id: int
    region_code: str
    name: str
    parent_region_id: int | None = None
    region_type: str | None = None
    country_code: str | None = None
    station_count: int = 0
    source: SourceInfo


class RegionDetail(RegionSummary):
    boundary_geojson: dict | list | None = None
    child_regions: list[RegionSummary] = Field(default_factory=list)


class OperatorSummary(BaseModel):
    id: int
    operator_code: str | None = None
    operator_name: str
    station_count: int = 0
    source: SourceInfo


class OperatorDetail(OperatorSummary):
    website_url: str | None = None
    stations: list["StationListItem"] = Field(default_factory=list)


class StationListItem(BaseModel):
    id: int
    external_station_id: int
    external_station_key: str | None = None
    station_name: str
    street_address: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    country_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    station_status: str
    access_type: str
    facility_type: str | None = None
    charging_types: list[str] = Field(default_factory=list)
    total_connector_count: int = 0
    date_last_confirmed: str | None = None
    effective_date: str | None = None
    region: RegionSummary | None = None
    operator: OperatorSummary | None = None
    source: SourceInfo


class StationDetail(StationListItem):
    connectors: list["ConnectorItem"] = Field(default_factory=list)
    related: dict[str, dict[str, int | str]] = Field(default_factory=dict)


class ConnectorItem(BaseModel):
    id: int
    station_id: int
    connector_type: str
    quantity: int = 0
    power_kw: float | None = None
    connector_status: str | None = None
    source: SourceInfo


class PageMeta(BaseModel):
    page: int
    page_size: int
    total: int
    has_next: bool


class RegionListResponse(BaseModel):
    items: list[RegionSummary]
    page: PageMeta


class OperatorListResponse(BaseModel):
    items: list[OperatorSummary]
    page: PageMeta


class StationListResponse(BaseModel):
    items: list[StationListItem]
    page: PageMeta


class ConnectorListResponse(BaseModel):
    items: list[ConnectorItem]
    page: PageMeta


class MapPoint(BaseModel):
    id: int
    station_name: str
    latitude: float
    longitude: float
    station_status: str
    access_type: str
    total_connector_count: int = 0
    source_type: str
    data_version: str
    region_code: str | None = None
    operator_name: str | None = None


class MapPointResponse(BaseModel):
    items: list[MapPoint]
    total: int


class StationQuery(BaseModel):
    region_code: str | None = None
    operator_id: int | None = Field(default=None, ge=1)
    station_status: str | None = None
    access_type: str | None = None
    charging_type: str | None = None
    source_type: Literal["public", "user_upload", "synthetic", "agent"] | None = None
    data_version: str | None = None
    min_latitude: float | None = Field(default=None, ge=-90, le=90)
    max_latitude: float | None = Field(default=None, ge=-90, le=90)
    min_longitude: float | None = Field(default=None, ge=-180, le=180)
    max_longitude: float | None = Field(default=None, ge=-180, le=180)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_km: float | None = Field(default=None, gt=0, le=500)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=200)


class ConnectorQuery(BaseModel):
    station_id: int | None = Field(default=None, ge=1)
    connector_type: str | None = None
    connector_status: str | None = None
    source_type: Literal["public", "user_upload", "synthetic", "agent"] | None = None
    data_version: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=500)


OperatorDetail.model_rebuild()
StationDetail.model_rebuild()
