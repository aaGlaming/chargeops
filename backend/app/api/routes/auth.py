from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.context import current_trace_id
from app.schemas.auth import ConfirmationRequest, ConfirmationResponse, LoginRequest, MeResponse, TokenResponse, UserSummary
from app.services.auth import (
    UserContext,
    authenticate_user,
    current_user_from_token,
    record_audit_event,
    require_high_risk_confirmation,
)
from app.db import get_db


router = APIRouter(prefix="/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def _summary(user: UserContext) -> UserSummary:
    return UserSummary(id=user.user_id, username=user.username, display_name=user.display_name, status=user.status, roles=sorted(user.role_codes))


def get_current_user(token: str | None = Depends(oauth2_scheme), session: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> UserContext:
    return current_user_from_token(session, token=token, settings=settings)


@router.post("/login", response_model=TokenResponse, summary="Issue an access token")
def login(payload: LoginRequest, session: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> TokenResponse:
    user, token, expires_in = authenticate_user(session, username=payload.username, password=payload.password.get_secret_value(), settings=settings)
    return TokenResponse(access_token=token, expires_in=expires_in, user=_summary(user))


@router.get("/me", response_model=MeResponse, summary="Get current user")
def me(user: UserContext = Depends(get_current_user)) -> MeResponse:
    summary = _summary(user)
    return MeResponse(**summary.model_dump(), permissions=sorted(user.permissions), readable_datasets=sorted(user.readable_datasets), writable_datasets=sorted(user.writable_datasets), allowed_regions=sorted(user.allowed_regions), dataset_regions={key: sorted(value) for key, value in user.dataset_regions.items()})


@router.post("/confirmations", response_model=ConfirmationResponse, summary="Record a human confirmation")
def confirm(payload: ConfirmationRequest, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> ConfirmationResponse:
    permission_code = require_high_risk_confirmation(user, payload.confirmation_type, session=session)
    status = "APPROVED" if payload.decision == "APPROVE" else "REJECTED"
    record_audit_event(
        session,
        action="MANUAL_CONFIRMATION",
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
        actor_user_id=user.user_id,
        severity="INFO" if status == "APPROVED" else "WARNING",
        after_state={"status": status, "confirmation_type": payload.confirmation_type, "comment": payload.comment},
        metadata={"permission": permission_code},
        commit=True,
    )
    return ConfirmationResponse(status=status, confirmation_type=payload.confirmation_type, resource_type=payload.resource_type, resource_id=payload.resource_id, actor_user_id=user.user_id, trace_id=current_trace_id())
