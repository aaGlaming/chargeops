"""Authorization guard for Agent tool implementations."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.errors import AppError
from app.services.auth import UserContext, enforce_data_scope, require_high_risk_confirmation, require_permission


def authorize_tool(
    user: UserContext,
    *,
    permission_code: str,
    dataset_type: str | None = None,
    region_code: str | None = None,
    write: bool = False,
    confirmation_type: str | None = None,
    session: Session | None = None,
) -> None:
    require_permission(user, permission_code, session=session)
    if dataset_type:
        enforce_data_scope(user, dataset_type=dataset_type, write=write, region_code=region_code)
    if confirmation_type:
        require_high_risk_confirmation(user, confirmation_type, session=session)


def ensure_idempotency_key(idempotency_key: str | None) -> str:
    if not idempotency_key:
        raise AppError("IDEMPOTENCY_KEY_REQUIRED", "高风险写操作必须提供幂等键", status_code=400)
    if len(idempotency_key) > 255:
        raise AppError("IDEMPOTENCY_KEY_INVALID", "幂等键长度不能超过 255", status_code=400)
    return idempotency_key
