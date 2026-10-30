from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app.config import Settings, get_settings
from app.context import current_trace_id
from app.schemas.system import HealthResponse, ReadyResponse
from app.services.readiness import readiness_report


router = APIRouter(tags=["system"])


def get_route_settings() -> Settings:
    return get_settings()


@router.get("/health", response_model=HealthResponse, summary="Liveness check")
def health(settings: Settings = Depends(get_route_settings)) -> HealthResponse:
    return HealthResponse(status="ok", service=settings.app_name, version=settings.app_version, trace_id=current_trace_id())


@router.get("/ready", response_model=ReadyResponse, summary="Dependency readiness check")
def ready(response: Response, settings: Settings = Depends(get_route_settings)) -> ReadyResponse:
    report = readiness_report(settings)
    if not report["ready"]:
        response.status_code = 503
    return ReadyResponse(**report, trace_id=current_trace_id(), config=settings.public_summary())
