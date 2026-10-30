from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user
from app.db import get_db
from app.errors import AppError
from app.schemas.operations import (
    CandidateDetail,
    CandidateItem,
    CandidateListResponse,
    CandidateStatusUpdate,
    CandidateWrite,
    FaultCreate,
    FaultItem,
    FaultListResponse,
    FaultQuery,
    FaultUpdate,
    MetricItem,
    MetricListResponse,
    MetricQuery,
)
from app.services.auth import UserContext, require_permission
from app.services.operations import (
    create_candidate,
    create_fault,
    delete_candidate,
    get_candidate,
    list_candidates,
    list_faults,
    list_metrics,
    update_candidate,
    update_candidate_status,
    update_fault,
)


router = APIRouter(tags=["operations"])


def _page_model(page: dict) -> dict:
    return page


@router.get("/metrics", response_model=MetricListResponse, summary="List station operation metrics")
def metrics(query: MetricQuery = Depends(), user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> MetricListResponse:
    require_permission(user, "metric.read", session=session)
    items, total = list_metrics(session, query)
    return MetricListResponse(items=[MetricItem(**item) for item in items], page=_page_model({"page": query.page, "page_size": query.page_size, "total": total, "has_next": query.page * query.page_size < total}))


@router.get("/stations/{station_id}/metrics", response_model=MetricListResponse, summary="List metrics for a station")
def station_metrics(station_id: int, query: MetricQuery = Depends(), user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> MetricListResponse:
    query = query.model_copy(update={"station_id": station_id})
    return metrics(query=query, user=user, session=session)


@router.get("/faults", response_model=FaultListResponse, summary="List station fault events")
def faults(query: FaultQuery = Depends(), user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> FaultListResponse:
    require_permission(user, "fault.read", session=session)
    items, total = list_faults(session, query)
    return FaultListResponse(items=[FaultItem(**item) for item in items], page={"page": query.page, "page_size": query.page_size, "total": total, "has_next": query.page * query.page_size < total})


@router.get("/stations/{station_id}/faults", response_model=FaultListResponse, summary="List faults for a station")
def station_faults(station_id: int, query: FaultQuery = Depends(), user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> FaultListResponse:
    query = query.model_copy(update={"station_id": station_id})
    return faults(query=query, user=user, session=session)


@router.post("/stations/{station_id}/faults", response_model=FaultItem, status_code=status.HTTP_201_CREATED, summary="Create a fault event")
def create_station_fault(station_id: int, payload: FaultCreate, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> FaultItem:
    require_permission(user, "fault.write", session=session)
    try:
        return FaultItem(**create_fault(session, station_id, payload, user))
    except LookupError as exc:
        raise AppError("STATION_NOT_FOUND", "充电站不存在", status_code=404, details={"station_id": station_id}) from exc
    except ValueError as exc:
        raise AppError("INVALID_FAULT", str(exc), status_code=400) from exc
    except IntegrityError as exc:
        session.rollback()
        raise AppError("FAULT_CONFLICT", "故障事件与已有记录冲突", status_code=409) from exc


@router.patch("/faults/{fault_id}", response_model=FaultItem, summary="Update fault recovery or severity")
def patch_fault(fault_id: int, payload: FaultUpdate, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> FaultItem:
    require_permission(user, "fault.write", session=session)
    try:
        return FaultItem(**update_fault(session, fault_id, payload, user))
    except LookupError as exc:
        raise AppError("FAULT_NOT_FOUND", "故障事件不存在", status_code=404, details={"fault_id": fault_id}) from exc
    except ValueError as exc:
        raise AppError("INVALID_FAULT", str(exc), status_code=400) from exc


@router.get("/candidate-sites", response_model=CandidateListResponse, summary="List candidate sites")
def candidate_sites(
    region_code: str | None = None,
    lifecycle_status: str | None = None,
    data_status: str | None = None,
    source_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    user: UserContext = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> CandidateListResponse:
    require_permission(user, "candidate.read", session=session)
    items, total = list_candidates(session, region_code=region_code, lifecycle_status=lifecycle_status, data_status=data_status, source_type=source_type, page=page, page_size=page_size)
    return CandidateListResponse(items=[CandidateItem(**item) for item in items], page={"page": page, "page_size": page_size, "total": total, "has_next": page * page_size < total})


@router.post("/candidate-sites", response_model=CandidateDetail, status_code=status.HTTP_201_CREATED, summary="Create a candidate site")
def create_candidate_site(payload: CandidateWrite, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> CandidateDetail:
    require_permission(user, "candidate.write", session=session)
    try:
        return CandidateDetail(**create_candidate(session, payload, user))
    except LookupError as exc:
        raise AppError("REGION_NOT_FOUND", "候选站点区域不存在", status_code=404) from exc
    except ValueError as exc:
        raise AppError("CANDIDATE_NOT_EVALUABLE", str(exc), status_code=422) from exc
    except IntegrityError as exc:
        session.rollback()
        raise AppError("CANDIDATE_CONFLICT", "候选站点外部 ID 与版本已存在", status_code=409) from exc


@router.get("/candidate-sites/{candidate_id}", response_model=CandidateDetail, summary="Get candidate site detail")
def candidate_site_detail(candidate_id: int, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> CandidateDetail:
    require_permission(user, "candidate.read", session=session)
    item = get_candidate(session, candidate_id)
    if item is None:
        raise AppError("CANDIDATE_NOT_FOUND", "候选站点不存在", status_code=404, details={"candidate_id": candidate_id})
    return CandidateDetail(**item)


@router.patch("/candidate-sites/{candidate_id}", response_model=CandidateDetail, summary="Update a candidate site")
def patch_candidate_site(candidate_id: int, payload: CandidateWrite, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> CandidateDetail:
    require_permission(user, "candidate.write", session=session)
    try:
        return CandidateDetail(**update_candidate(session, candidate_id, payload, user))
    except LookupError as exc:
        raise AppError("CANDIDATE_NOT_FOUND", "候选站点不存在", status_code=404, details={"candidate_id": candidate_id}) from exc
    except ValueError as exc:
        raise AppError("CANDIDATE_NOT_EVALUABLE", str(exc), status_code=422) from exc


@router.post("/candidate-sites/{candidate_id}/status", response_model=CandidateDetail, summary="Change candidate lifecycle status")
def candidate_status(candidate_id: int, payload: CandidateStatusUpdate, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> CandidateDetail:
    require_permission(user, "candidate.write", session=session)
    try:
        return CandidateDetail(**update_candidate_status(session, candidate_id, payload.lifecycle_status, payload.reason, user))
    except LookupError as exc:
        raise AppError("CANDIDATE_NOT_FOUND", "候选站点不存在", status_code=404, details={"candidate_id": candidate_id}) from exc
    except ValueError as exc:
        raise AppError("CANDIDATE_NOT_EVALUABLE", str(exc), status_code=422) from exc


@router.delete("/candidate-sites/{candidate_id}", response_model=None, status_code=status.HTTP_204_NO_CONTENT, summary="Soft delete candidate site")
def remove_candidate_site(candidate_id: int, response: Response, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> None:
    require_permission(user, "candidate.write", session=session)
    try:
        delete_candidate(session, candidate_id, user)
    except LookupError as exc:
        raise AppError("CANDIDATE_NOT_FOUND", "候选站点不存在", status_code=404, details={"candidate_id": candidate_id}) from exc
    response.status_code = status.HTTP_204_NO_CONTENT
