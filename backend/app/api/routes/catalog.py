from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user
from app.db import get_db
from app.errors import AppError
from app.schemas.catalog import (
    ConnectorListResponse,
    ConnectorQuery,
    MapPointResponse,
    OperatorDetail,
    OperatorListResponse,
    RegionDetail,
    RegionListResponse,
    StationDetail,
    StationListResponse,
    StationQuery,
)
from app.services.auth import UserContext, require_permission
from app.services.catalog import (
    get_operator,
    get_region,
    get_station,
    list_connectors,
    list_operators,
    list_regions,
    list_stations,
    map_points,
    page_meta,
)


router = APIRouter(tags=["catalog"])


def authorize_catalog(user: UserContext, session: Session) -> None:
    require_permission(user, "station.read", session=session)


@router.get("/regions", response_model=RegionListResponse, summary="List regions")
def regions(
    region_code: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    user: UserContext = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> RegionListResponse:
    authorize_catalog(user, session)
    items, total = list_regions(session, region_code=region_code, page=page, page_size=page_size)
    return RegionListResponse(items=items, page=page_meta(page, page_size, total))


@router.get("/regions/{region_code}", response_model=RegionDetail, summary="Get region detail")
def region_detail(region_code: str, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> RegionDetail:
    authorize_catalog(user, session)
    result = get_region(session, region_code)
    if result is None:
        raise AppError("REGION_NOT_FOUND", "区域不存在", status_code=404, details={"region_code": region_code})
    summary, children = result
    return RegionDetail(**summary.model_dump(), child_regions=children)


@router.get("/operators", response_model=OperatorListResponse, summary="List operators")
def operators(
    operator_name: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    user: UserContext = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> OperatorListResponse:
    authorize_catalog(user, session)
    items, total = list_operators(session, operator_name=operator_name, page=page, page_size=page_size)
    return OperatorListResponse(items=items, page=page_meta(page, page_size, total))


@router.get("/operators/{operator_id}", response_model=OperatorDetail, summary="Get operator detail")
def operator_detail(operator_id: int, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> OperatorDetail:
    authorize_catalog(user, session)
    result = get_operator(session, operator_id)
    if result is None:
        raise AppError("OPERATOR_NOT_FOUND", "运营商不存在", status_code=404, details={"operator_id": operator_id})
    summary, stations = result
    return OperatorDetail(**summary.model_dump(), stations=stations)


@router.get("/stations", response_model=StationListResponse, summary="List charging stations")
def stations(query: StationQuery = Depends(), user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> StationListResponse:
    authorize_catalog(user, session)
    try:
        items, total = list_stations(session, query)
    except ValueError as exc:
        raise AppError("INVALID_STATION_FILTER", str(exc), status_code=400) from exc
    return StationListResponse(items=items, page=page_meta(query.page, query.page_size, total))


@router.get("/stations/map-points", response_model=MapPointResponse, summary="Get station map points")
def station_map_points(
    query: StationQuery = Depends(),
    limit: int = Query(default=5000, ge=1, le=10000),
    user: UserContext = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> MapPointResponse:
    authorize_catalog(user, session)
    try:
        items, total = map_points(session, query, limit=limit)
    except ValueError as exc:
        raise AppError("INVALID_STATION_FILTER", str(exc), status_code=400) from exc
    return MapPointResponse(items=items, total=total)


@router.get("/stations/{station_id}/connectors", response_model=ConnectorListResponse, summary="List station connectors")
def station_connectors(
    station_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    user: UserContext = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> ConnectorListResponse:
    authorize_catalog(user, session)
    items, total = list_connectors(session, ConnectorQuery(station_id=station_id, page=page, page_size=page_size))
    return ConnectorListResponse(items=items, page=page_meta(page, page_size, total))


@router.get("/stations/{station_id}/map-point", response_model=MapPointResponse, summary="Get one station map point")
def station_map_point(station_id: int, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> MapPointResponse:
    authorize_catalog(user, session)
    item = get_station(session, station_id)
    if item is None:
        raise AppError("STATION_NOT_FOUND", "充电站不存在", status_code=404, details={"station_id": station_id})
    point = MapPointResponse(items=[{
        "id": item["id"], "station_name": item["station_name"], "latitude": item["latitude"], "longitude": item["longitude"],
        "station_status": item["station_status"], "access_type": item["access_type"], "total_connector_count": item["total_connector_count"],
        "source_type": item["source"].source_type, "data_version": item["source"].data_version,
        "region_code": item["region"].region_code if item["region"] else None, "operator_name": item["operator"].operator_name if item["operator"] else None,
    }], total=1)
    return point


@router.get("/stations/{station_id}", response_model=StationDetail, summary="Get station detail")
def station_detail(station_id: int, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> StationDetail:
    authorize_catalog(user, session)
    item = get_station(session, station_id)
    if item is None:
        raise AppError("STATION_NOT_FOUND", "充电站不存在", status_code=404, details={"station_id": station_id})
    return StationDetail(**item)


@router.get("/connectors", response_model=ConnectorListResponse, summary="List connectors")
def connectors(query: ConnectorQuery = Depends(), user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> ConnectorListResponse:
    authorize_catalog(user, session)
    items, total = list_connectors(session, query)
    return ConnectorListResponse(items=items, page=page_meta(query.page, query.page_size, total))
