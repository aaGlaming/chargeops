"""Authentication, authorization, data-scope and audit services."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.authorization import (
    DEFAULT_DATASET_READ,
    DEFAULT_DATASET_WRITE,
    HIGH_RISK_CONFIRMATION_PERMISSIONS,
    PERMISSION_DEFINITIONS,
    ROLE_DEFINITIONS,
    ROLE_PERMISSION_CODES,
)
from app.config import Settings
from app.context import current_request_id, current_trace_id, user_id_var
from app.errors import AppError
from app.security import create_access_token, decode_access_token, hash_password, verify_password


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UserContext:
    user_id: int
    username: str
    display_name: str
    status: str
    token_version: int
    role_codes: frozenset[str] = field(default_factory=frozenset)
    permissions: frozenset[str] = field(default_factory=frozenset)
    readable_datasets: frozenset[str] = field(default_factory=frozenset)
    writable_datasets: frozenset[str] = field(default_factory=frozenset)
    allowed_regions: frozenset[str] = field(default_factory=lambda: frozenset({"*"}))
    dataset_regions: dict[str, frozenset[str]] = field(default_factory=dict)

    def has_permission(self, permission_code: str) -> bool:
        return permission_code in self.permissions

    def can_access_dataset(self, dataset_type: str, *, write: bool = False, region_code: str | None = None) -> bool:
        datasets = self.writable_datasets if write else self.readable_datasets
        if dataset_type not in datasets:
            return False
        regions = self.dataset_regions.get(dataset_type, self.allowed_regions)
        return not regions or "*" in regions or not region_code or region_code in regions


def _json(value: Any) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False, default=str)


def record_audit_event(
    session: Session,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    actor_user_id: int | None = None,
    severity: str = "INFO",
    before_state: Any = None,
    after_state: Any = None,
    metadata: Any = None,
    commit: bool = False,
) -> None:
    session.execute(
        text(
            """INSERT INTO audit_log
            (occurred_at, actor_user_id, action, resource_type, resource_id,
             request_id, trace_id, severity, before_state, after_state, metadata)
            VALUES (:occurred_at, :actor_user_id, :action, :resource_type, :resource_id,
                    :request_id, :trace_id, :severity, :before_state, :after_state, :metadata)"""
        ),
        {
            "occurred_at": datetime.now(UTC).replace(tzinfo=None),
            "actor_user_id": actor_user_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "request_id": current_request_id(),
            "trace_id": current_trace_id(),
            "severity": severity,
            "before_state": _json(before_state),
            "after_state": _json(after_state),
            "metadata": _json(metadata),
        },
    )
    if commit:
        session.commit()


def seed_authorization(session: Session) -> dict[str, int]:
    """Idempotently create the six roles and the menu/API/tool permissions."""
    now = datetime.now(UTC).replace(tzinfo=None)
    permission_ids: dict[str, int] = {}
    for definition in PERMISSION_DEFINITIONS:
        session.execute(
            text(
                """INSERT INTO permissions(permission_code, resource, action, description, created_at)
                VALUES (:code, :resource, :action, :description, :created_at)
                ON DUPLICATE KEY UPDATE resource=:resource, action=:action, description=:description"""
            ),
            {"code": definition.code, "resource": definition.resource, "action": definition.action, "description": definition.description, "created_at": now},
        )
        permission_ids[definition.code] = int(session.execute(text("SELECT id FROM permissions WHERE permission_code=:code"), {"code": definition.code}).scalar_one())

    role_ids: dict[str, int] = {}
    for role_code, role_name, description in ROLE_DEFINITIONS:
        session.execute(
            text(
                """INSERT INTO roles(role_code, role_name, description, created_at, updated_at)
                VALUES (:code, :name, :description, :created_at, :updated_at)
                ON DUPLICATE KEY UPDATE role_name=:name, description=:description, updated_at=:updated_at"""
            ),
            {"code": role_code, "name": role_name, "description": description, "created_at": now, "updated_at": now},
        )
        role_ids[role_code] = int(session.execute(text("SELECT id FROM roles WHERE role_code=:code"), {"code": role_code}).scalar_one())

    for role_code, codes in ROLE_PERMISSION_CODES.items():
        for permission_code in codes:
            session.execute(
                text(
                    """INSERT INTO role_permission(role_id, permission_id, granted_at)
                    VALUES (:role_id, :permission_id, :granted_at)
                    ON DUPLICATE KEY UPDATE granted_at=granted_at"""
                ),
                {"role_id": role_ids[role_code], "permission_id": permission_ids[permission_code], "granted_at": now},
            )
    session.commit()
    return role_ids


def create_or_update_user(session: Session, *, username: str, password: str, display_name: str, email: str | None, role_codes: list[str], settings: Settings, assigned_by: int | None = None) -> int:
    if not role_codes or any(code not in ROLE_PERMISSION_CODES for code in role_codes):
        raise ValueError("at least one known role is required")
    now = datetime.now(UTC).replace(tzinfo=None)
    password_hash = hash_password(password, settings.password_hash_iterations)
    existing = session.execute(text("SELECT id FROM users WHERE username=:username"), {"username": username}).scalar_one_or_none()
    if existing is None:
        session.execute(
            text(
                """INSERT INTO users(username, display_name, email, password_hash, status, token_version, created_at, updated_at)
                VALUES (:username, :display_name, :email, :password_hash, 'ACTIVE', 1, :created_at, :updated_at)"""
            ),
            {"username": username, "display_name": display_name, "email": email, "password_hash": password_hash, "created_at": now, "updated_at": now},
        )
        user_id = int(session.execute(text("SELECT id FROM users WHERE username=:username"), {"username": username}).scalar_one())
    else:
        user_id = int(existing)
        session.execute(
            text("UPDATE users SET display_name=:display_name, email=:email, password_hash=:password_hash, status='ACTIVE', token_version=token_version+1, updated_at=:updated_at WHERE id=:id"),
            {"display_name": display_name, "email": email, "password_hash": password_hash, "updated_at": now, "id": user_id},
        )
        session.execute(text("DELETE FROM user_role WHERE user_id=:user_id"), {"user_id": user_id})

    role_ids: dict[str, int] = {}
    for role_code in role_codes:
        role_id = session.execute(text("SELECT id FROM roles WHERE role_code=:role_code"), {"role_code": role_code}).scalar_one_or_none()
        if role_id is not None:
            role_ids[role_code] = int(role_id)
    for role_code in role_codes:
        if role_code not in role_ids:
            raise ValueError(f"role is not seeded: {role_code}")
        session.execute(
            text("INSERT INTO user_role(user_id, role_id, assigned_by, assigned_at) VALUES (:user_id, :role_id, :assigned_by, :assigned_at) ON DUPLICATE KEY UPDATE assigned_at=assigned_at"),
            {"user_id": user_id, "role_id": role_ids[role_code], "assigned_by": assigned_by, "assigned_at": now},
        )
    session.commit()
    return user_id


def _load_user_row(session: Session, user_id: int):
    return session.execute(
        text("SELECT id, username, display_name, status, token_version FROM users WHERE id=:id AND deleted_at IS NULL"),
        {"id": user_id},
    ).mappings().one_or_none()


def load_user_context(session: Session, user_id: int) -> UserContext | None:
    user = _load_user_row(session, user_id)
    if user is None or user["status"] != "ACTIVE":
        return None
    roles = frozenset(session.execute(text("SELECT r.role_code FROM user_role ur JOIN roles r ON r.id=ur.role_id WHERE ur.user_id=:user_id"), {"user_id": user_id}).scalars().all())
    permissions = frozenset(session.execute(text("SELECT DISTINCT p.permission_code FROM user_role ur JOIN role_permission rp ON rp.role_id=ur.role_id JOIN permissions p ON p.id=rp.permission_id WHERE ur.user_id=:user_id"), {"user_id": user_id}).scalars().all())
    scope_rows = session.execute(text("SELECT region_code, dataset_type, can_read, can_write FROM user_data_scope WHERE user_id=:user_id"), {"user_id": user_id}).mappings().all()
    default_roles = roles or frozenset()
    readable = set().union(*(DEFAULT_DATASET_READ.get(role, frozenset()) for role in default_roles))
    writable = set().union(*(DEFAULT_DATASET_WRITE.get(role, frozenset()) for role in default_roles))
    regions: set[str] = set()
    dataset_regions: dict[str, set[str]] = {}
    if scope_rows:
        readable = {row["dataset_type"] for row in scope_rows if row["can_read"]}
        writable = {row["dataset_type"] for row in scope_rows if row["can_write"]}
        regions = {row["region_code"] for row in scope_rows}
        for row in scope_rows:
            dataset_regions.setdefault(row["dataset_type"], set()).add(row["region_code"])
    else:
        for dataset_type in readable | writable:
            dataset_regions[dataset_type] = {"*"}
    return UserContext(
        user_id=int(user["id"]), username=user["username"], display_name=user["display_name"], status=user["status"],
        token_version=int(user["token_version"]), role_codes=default_roles, permissions=permissions,
        readable_datasets=frozenset(readable), writable_datasets=frozenset(writable),
        allowed_regions=frozenset(regions or {"*"}),
        dataset_regions={key: frozenset(value) for key, value in dataset_regions.items()},
    )


def authenticate_user(session: Session, *, username: str, password: str, settings: Settings) -> tuple[UserContext, str, int]:
    row = session.execute(text("SELECT id, password_hash, status FROM users WHERE username=:username AND deleted_at IS NULL"), {"username": username}).mappings().one_or_none()
    if row is None or row["status"] != "ACTIVE" or not verify_password(password, row["password_hash"]):
        record_audit_event(session, action="LOGIN_FAILED", resource_type="user", resource_id=username, severity="WARNING", metadata={"reason": "invalid_credentials"}, commit=True)
        raise AppError("AUTHENTICATION_FAILED", "用户名或密码错误", status_code=401, headers={"WWW-Authenticate": "Bearer"})
    user_id = int(row["id"])
    session.execute(text("UPDATE users SET last_login_at=:now, updated_at=:now WHERE id=:id"), {"now": datetime.now(UTC).replace(tzinfo=None), "id": user_id})
    user = load_user_context(session, user_id)
    if user is None:
        session.rollback()
        raise AppError("AUTHENTICATION_FAILED", "用户不可用", status_code=401, headers={"WWW-Authenticate": "Bearer"})
    token, expires_in = create_access_token(user_id=user.user_id, username=user.username, token_version=user.token_version, roles=sorted(user.role_codes), settings=settings)
    record_audit_event(session, action="LOGIN_SUCCEEDED", resource_type="user", resource_id=str(user.user_id), actor_user_id=user.user_id, metadata={"roles": sorted(user.role_codes)}, commit=True)
    return user, token, expires_in


def current_user_from_token(session: Session, *, token: str | None, settings: Settings) -> UserContext:
    if not token:
        raise AppError("AUTHENTICATION_REQUIRED", "需要 Bearer Token", status_code=401, headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = decode_access_token(token, settings)
        user_id = int(claims["sub"])
        token_version = int(claims["tv"])
    except (ValueError, TypeError, KeyError):
        record_audit_event(session, action="TOKEN_VALIDATION_FAILED", resource_type="token", severity="WARNING", metadata={"reason": "invalid_or_expired"}, commit=True)
        raise AppError("INVALID_TOKEN", "Token 无效或已过期", status_code=401, headers={"WWW-Authenticate": "Bearer"})
    user = load_user_context(session, user_id)
    if user is None or user.token_version != token_version:
        record_audit_event(session, action="TOKEN_VALIDATION_FAILED", resource_type="user", resource_id=str(user_id), severity="WARNING", metadata={"reason": "revoked_or_inactive"}, commit=True)
        raise AppError("INVALID_TOKEN", "Token 已撤销或用户已停用", status_code=401, headers={"WWW-Authenticate": "Bearer"})
    user_id_var.set(user.user_id)
    return user


def require_permission(user: UserContext, permission_code: str, session: Session | None = None) -> None:
    if user.has_permission(permission_code):
        return
    if session is not None:
        record_audit_event(
            session,
            action="PERMISSION_DENIED",
            resource_type="permission",
            resource_id=permission_code,
            actor_user_id=user.user_id,
            severity="WARNING",
            metadata={"username": user.username},
            commit=True,
        )
    raise AppError("PERMISSION_DENIED", "当前用户没有执行该操作的权限", status_code=403, details={"permission": permission_code})


def enforce_data_scope(user: UserContext, *, dataset_type: str, write: bool = False, region_code: str | None = None) -> None:
    if user.can_access_dataset(dataset_type, write=write, region_code=region_code):
        return
    raise AppError("DATA_SCOPE_DENIED", "当前用户没有访问该数据范围的权限", status_code=403, details={"dataset_type": dataset_type, "write": write, "region_code": region_code})


def require_high_risk_confirmation(user: UserContext, confirmation_type: str, session: Session | None = None) -> str:
    permission_code = HIGH_RISK_CONFIRMATION_PERMISSIONS.get(confirmation_type)
    if permission_code is None:
        raise AppError("INVALID_CONFIRMATION_TYPE", "不支持的人工确认类型", status_code=400)
    require_permission(user, permission_code, session=session)
    return permission_code
