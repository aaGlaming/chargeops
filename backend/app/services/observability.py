"""Audit querying and operational monitoring services."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT, Settings
from app.schemas.observability import AlertState, AuditLogItem, AuditLogListResponse, MonitoringOverview
from app.services.auth import UserContext, record_audit_event, require_permission
from app.services.readiness import readiness_report
from app.telemetry import snapshot


_ALERTS: dict[str, dict[str, str]] = {
    "mysql_unavailable": {"label": "MySQL 不可用", "severity": "CRITICAL"},
    "chroma_unavailable": {"label": "Chroma 不可用", "severity": "CRITICAL"},
    "model_unavailable": {"label": "模型服务不可用", "severity": "HIGH"},
    "high_error_rate": {"label": "API 错误率过高", "severity": "HIGH"},
    "high_latency": {"label": "API P95 延迟过高", "severity": "MEDIUM"},
}
_DISABLED_ALERTS: set[str] = set()


def _decode(value: Any) -> dict[str, Any] | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except json.JSONDecodeError:
            return {"value": value}
    return value if isinstance(value, dict) else {"value": value}


def list_audit_logs(
    session: Session,
    user: UserContext,
    *,
    page: int = 1,
    page_size: int = 50,
    action: str | None = None,
    resource_type: str | None = None,
    severity: str | None = None,
    trace_id: str | None = None,
    agent_run_id: str | None = None,
    import_batch_id: int | None = None,
) -> AuditLogListResponse:
    require_permission(user, "audit.read", session=session)
    conditions = ["1=1"]
    params: dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}
    for value, key in ((action, "action"), (resource_type, "resource_type"), (severity, "severity"), (trace_id, "trace_id"), (agent_run_id, "agent_run_id")):
        if value:
            conditions.append(f"{key} LIKE :{key}")
            params[key] = f"%{value}%"
    if import_batch_id is not None:
        conditions.append("import_batch_id=:import_batch_id")
        params["import_batch_id"] = import_batch_id
    where = " AND ".join(conditions)
    rows = session.execute(text(f"SELECT * FROM audit_log WHERE {where} ORDER BY occurred_at DESC, id DESC LIMIT :limit OFFSET :offset"), params).mappings().all()
    total = int(session.execute(text(f"SELECT COUNT(*) FROM audit_log WHERE {where}"), {key: value for key, value in params.items() if key not in {"limit", "offset"}}).scalar_one())
    items = [AuditLogItem(
        id=int(row["id"]), occurred_at=row["occurred_at"], actor_user_id=int(row["actor_user_id"]) if row.get("actor_user_id") is not None else None,
        action=row["action"], resource_type=row["resource_type"], resource_id=row.get("resource_id"), request_id=row.get("request_id"), trace_id=row.get("trace_id"),
        agent_run_id=row.get("agent_run_id"), tool_call_id=int(row["resource_id"]) if row.get("resource_type") == "tool_call" and str(row.get("resource_id") or "").isdigit() else None,
        import_batch_id=int(row["import_batch_id"]) if row.get("import_batch_id") is not None else None,
        severity=row["severity"], before_state=_decode(row.get("before_state")), after_state=_decode(row.get("after_state")), metadata=_decode(row.get("metadata")),
    ) for row in rows]
    return AuditLogListResponse(items=items, page={"page": page, "page_size": page_size, "total": total, "has_next": page * page_size < total})


def _count(session: Session, sql: str, params: dict[str, Any] | None = None) -> int:
    try:
        return int(session.execute(text(sql), params or {}).scalar_one() or 0)
    except Exception:
        return 0


def monitoring_overview(settings: Settings, session: Session, user: UserContext) -> MonitoringOverview:
    require_permission(user, "monitor.read", session=session)
    readiness = readiness_report(settings)
    telemetry = snapshot()
    disk = shutil.disk_usage(PROJECT_ROOT)
    run_rows = session.execute(text("SELECT status, COUNT(*) AS count FROM agent_run GROUP BY status")).mappings().all()
    import_rows = session.execute(text("SELECT status, COUNT(*) AS count FROM import_batch GROUP BY status")).mappings().all()
    run_counts = {str(row["status"]): int(row["count"]) for row in run_rows}
    import_counts = {str(row["status"]): int(row["count"]) for row in import_rows}
    audit_counts = {
        "total": _count(session, "SELECT COUNT(*) FROM audit_log"),
        "warnings": _count(session, "SELECT COUNT(*) FROM audit_log WHERE severity IN ('WARNING','ERROR')"),
        "last_24h": _count(session, "SELECT COUNT(*) FROM audit_log WHERE occurred_at >= UTC_TIMESTAMP() - INTERVAL 1 DAY"),
    }
    event_rows = session.execute(text("SELECT event_type, COUNT(*) AS count, AVG(duration_ms) AS avg_duration, MAX(duration_ms) AS max_duration FROM agent_run_event WHERE duration_ms IS NOT NULL GROUP BY event_type")).mappings().all()
    components = dict(telemetry.get("components", {}))
    for row in event_rows:
        key = {"MODEL_CALL": "model", "EMBEDDING_CALL": "embedding", "RAG_SEARCH": "rag_search", "DETERMINISTIC_CALCULATION": "deterministic"}.get(row["event_type"], str(row["event_type"]).lower())
        event_count = int(row["count"])
        event_p95 = float(row["max_duration"] or row["avg_duration"] or 0)
        current = components.get(key)
        if current is None:
            components[key] = {"count": event_count, "error_count": 0, "p95_latency_ms": event_p95}
        else:
            current["count"] = max(int(current.get("count", 0)), event_count)
            current["p95_latency_ms"] = max(float(current.get("p95_latency_ms", 0)), event_p95)
    return MonitoringOverview(
        generated_at=datetime.now(UTC).replace(tzinfo=None), readiness=readiness, telemetry=telemetry,
        database={"status": next((item["status"] for item in readiness["checks"] if item["service"] == "mysql"), "unknown")},
        disk={"total_bytes": disk.total, "used_bytes": disk.used, "free_bytes": disk.free, "used_ratio": round(disk.used / disk.total, 4) if disk.total else 0},
        models=settings.public_summary(), agent_runs=run_counts, imports=import_counts, audit=audit_counts, components=components,
    )


def alert_states(overview: MonitoringOverview) -> list[AlertState]:
    checks = {item.get("service"): item for item in overview.readiness.get("checks", [])}
    conditions = {
        "mysql_unavailable": checks.get("mysql", {}).get("status") == "down",
        "chroma_unavailable": checks.get("chroma", {}).get("status") == "down",
        "model_unavailable": checks.get("chat", {}).get("status") == "down" or checks.get("embedding", {}).get("status") == "down",
        "high_error_rate": float(overview.telemetry.get("error_rate", 0)) >= 0.05,
        "high_latency": float(overview.telemetry.get("p95_latency_ms", 0)) >= 2000,
    }
    return [AlertState(code=code, label=value["label"], severity=value["severity"], enabled=code not in _DISABLED_ALERTS, current_status="ALERT" if conditions.get(code) else "OK", detail="当前检测到异常" if conditions.get(code) else "运行正常") for code, value in _ALERTS.items()]


def set_alert_enabled(session: Session, user: UserContext, code: str, enabled: bool) -> None:
    require_permission(user, "monitor.write", session=session)
    if code not in _ALERTS:
        raise ValueError("unknown alert code")
    if enabled:
        _DISABLED_ALERTS.discard(code)
        action = "ALERT_ENABLED"
    else:
        _DISABLED_ALERTS.add(code)
        action = "ALERT_DISABLED"
    record_audit_event(session, action=action, resource_type="alert", resource_id=code, actor_user_id=user.user_id, metadata={"enabled": enabled}, commit=True)
