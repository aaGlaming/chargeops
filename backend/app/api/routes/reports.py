from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user
from app.config import Settings, get_settings
from app.db import get_db
from app.errors import AppError
from app.schemas.reports import ReportConfirmationRequest, ReportCreateRequest, ReportDetail, ReportListResponse
from app.services.auth import UserContext, require_permission
from app.services.reports import archive_report, confirm_report, create_report, get_report, list_reports, render_markdown, report_json


router = APIRouter(prefix="/reports", tags=["reports"])


def _visible(user: UserContext, report: ReportDetail) -> bool:
    return report.created_by == user.user_id or bool({"SYSTEM_ADMIN", "AUDITOR"} & set(user.role_codes))


def _get_visible(report_id: str, user: UserContext, session: Session) -> ReportDetail:
    report = get_report(session, report_id)
    if report is None:
        raise AppError("REPORT_NOT_FOUND", "报告不存在", status_code=404)
    if not _visible(user, report):
        raise AppError("FORBIDDEN", "无权访问该报告", status_code=403)
    return report


@router.post("", response_model=ReportDetail, status_code=201, summary="Create a decision report from an Agent run")
def create_report_endpoint(request: ReportCreateRequest, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> ReportDetail:
    require_permission(user, "report.read", session=session)
    return create_report(session, user, run_id=request.run_id, title=request.title)


@router.get("", response_model=ReportListResponse, summary="List decision reports")
def reports_endpoint(report_type: str | None = Query(default=None), status: str | None = Query(default=None), user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> ReportListResponse:
    require_permission(user, "report.read", session=session)
    created_by = None if {"SYSTEM_ADMIN", "AUDITOR"} & set(user.role_codes) else user.user_id
    return list_reports(session, created_by=created_by, report_type=report_type, status=status)


@router.get("/{report_id}/export", summary="Export a decision report")
def export_report_endpoint(report_id: str, format: str = Query(default="markdown", pattern="^(markdown|json)$"), user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)):
    require_permission(user, "report.read", session=session)
    report = _get_visible(report_id, user, session)
    if format == "json":
        return JSONResponse(content=report_json(report), headers={"Content-Disposition": f'attachment; filename="chargeops-{report.report_id}.json"'})
    return PlainTextResponse(render_markdown(report), media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="chargeops-{report.report_id}.md"'})


@router.get("/{report_id}", response_model=ReportDetail, summary="Get a decision report")
def report_detail_endpoint(report_id: str, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> ReportDetail:
    require_permission(user, "report.read", session=session)
    return _get_visible(report_id, user, session)


@router.post("/{report_id}/confirmation", response_model=ReportDetail, summary="Approve or reject a decision report")
def report_confirmation_endpoint(report_id: str, request: ReportConfirmationRequest, settings: Settings = Depends(get_settings), user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> ReportDetail:
    require_permission(user, "report.confirm", session=session)
    _get_visible(report_id, user, session)
    return confirm_report(session, settings, user, report_id, decision=request.decision, comment=request.comment)


@router.post("/{report_id}/archive", response_model=ReportDetail, summary="Archive a decision report")
def archive_report_endpoint(report_id: str, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> ReportDetail:
    require_permission(user, "report.confirm", session=session)
    _get_visible(report_id, user, session)
    return archive_report(session, user, report_id)
