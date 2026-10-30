from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.routes.auth import get_current_user
from app.config import Settings, get_settings
from app.db import get_db
from app.errors import AppError
from app.schemas.observability import AlertListResponse, AuditLogListResponse, MonitoringOverview
from app.services.auth import UserContext
from app.services.observability import alert_states, list_audit_logs, monitoring_overview, set_alert_enabled


router = APIRouter(tags=["observability"])


@router.get("/audit-logs", response_model=AuditLogListResponse, summary="Query immutable audit logs")
def audit_logs(page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200), action: str | None = None, resource_type: str | None = None, severity: str | None = None, trace_id: str | None = None, agent_run_id: str | None = None, import_batch_id: int | None = Query(default=None, ge=1), user: UserContext = Depends(get_current_user), session=Depends(get_db)) -> AuditLogListResponse:
    return list_audit_logs(session, user, page=page, page_size=page_size, action=action, resource_type=resource_type, severity=severity, trace_id=trace_id, agent_run_id=agent_run_id, import_batch_id=import_batch_id)


@router.get("/monitoring/overview", response_model=MonitoringOverview, summary="Get operational monitoring overview")
def monitoring(settings: Settings = Depends(get_settings), user: UserContext = Depends(get_current_user), session=Depends(get_db)) -> MonitoringOverview:
    return monitoring_overview(settings, session, user)


@router.get("/monitoring/alerts", response_model=AlertListResponse, summary="List alert states")
def alerts(settings: Settings = Depends(get_settings), user: UserContext = Depends(get_current_user), session=Depends(get_db)) -> AlertListResponse:
    overview = monitoring_overview(settings, session, user)
    return AlertListResponse(items=alert_states(overview))


@router.post("/monitoring/alerts/{code}", response_model=AlertListResponse, summary="Enable or disable an alert")
def update_alert(code: str, enabled: bool = Query(...), settings: Settings = Depends(get_settings), user: UserContext = Depends(get_current_user), session=Depends(get_db)) -> AlertListResponse:
    try:
        set_alert_enabled(session, user, code, enabled)
    except ValueError as exc:
        raise AppError("ALERT_NOT_FOUND", str(exc), status_code=404) from exc
    overview = monitoring_overview(settings, session, user)
    return AlertListResponse(items=alert_states(overview))
