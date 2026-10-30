"""Agent run state, tool-call, model-call and confirmation event persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agents.contracts import (
    AgentStateSnapshot,
    AgentType,
    ConfirmationRecord,
    ModelCallRecord,
    ToolContract,
)
from app.errors import AppError
from app.schemas.agents import AgentRunCreateRequest, AgentRunDetail, AgentRunListResponse, AgentRunSummary
from app.services.auth import UserContext, _redact, record_audit_event
from app.telemetry import record_sample


TERMINAL_STATUSES = {"COMPLETED", "FAILED", "BLOCKED", "CANCELLED"}
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "PENDING": {"RUNNING", "CANCELLED"},
    "RUNNING": {"RUNNING", "WAITING_CONFIRMATION", "COMPLETED", "FAILED", "BLOCKED", "CANCELLED"},
    "WAITING_CONFIRMATION": {"RUNNING", "COMPLETED", "FAILED", "CANCELLED"},
    "COMPLETED": set(),
    "FAILED": {"RUNNING"},
    "BLOCKED": {"RUNNING"},
    "CANCELLED": set(),
}

INPUT_SCHEMAS: dict[str, type[Any]] = {}


def _load_input_schemas() -> dict[str, type[Any]]:
    from app.agents.contracts import CompetitionInput, CoverageGapInput, ExpansionInput, PolicyMatchingInput, SiteSelectionInput

    return {
        "coverage_gap": CoverageGapInput,
        "competition": CompetitionInput,
        "site_selection": SiteSelectionInput,
        "expansion": ExpansionInput,
        "policy_matching": PolicyMatchingInput,
    }


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _json(value: Any) -> str:
    return json.dumps(_redact(value), ensure_ascii=False, default=str)


def _decode(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return json.loads(value) if value else {}
    return value or {}


def validate_agent_input(agent_type: AgentType, payload: dict[str, Any]) -> dict[str, Any]:
    schema = _load_input_schemas().get(agent_type)
    if schema is None:
        raise AppError("AGENT_TYPE_UNSUPPORTED", "不支持的 Agent 类型", status_code=400)
    return schema.model_validate(payload).model_dump(mode="json")


def _summary(row: Any) -> AgentRunSummary:
    return AgentRunSummary(
        run_id=row["run_id"], agent_type=row["agent_type"], requested_by=int(row["requested_by"]), status=row["status"],
        data_version=row["data_version"], prompt_version=row["prompt_version"], model_name=row["model_name"], embedding_model=row["embedding_model"],
        stop_reason=row["stop_reason"], confirmation_status=row["confirmation_status"], started_at=row["started_at"], finished_at=row["finished_at"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def create_agent_run(session: Session, user: UserContext, request: AgentRunCreateRequest) -> AgentRunDetail:
    validated_input = validate_agent_input(request.agent_type, request.input_payload)
    run_id = str(uuid4())
    now = _now()
    snapshot = AgentStateSnapshot(
        run_id=run_id, agent_type=request.agent_type, user_input=validated_input, business_scope=request.business_scope,
        data_version=request.data_version, prompt_version=request.prompt_version, model_name=request.model_name,
        embedding_model=request.embedding_model,
    )
    session.execute(text("""INSERT INTO agent_run
        (run_id, agent_type, requested_by, input_payload, business_scope, data_version, prompt_version, model_name, embedding_model,
         status, confirmation_status, state_snapshot, created_at, updated_at)
        VALUES (:run_id, :agent_type, :requested_by, :input_payload, :business_scope, :data_version, :prompt_version, :model_name, :embedding_model,
         'PENDING', 'NOT_REQUIRED', :state_snapshot, :created_at, :updated_at)"""), {
        "run_id": run_id, "agent_type": request.agent_type, "requested_by": user.user_id, "input_payload": _json(validated_input),
        "business_scope": _json(request.business_scope), "data_version": request.data_version, "prompt_version": request.prompt_version,
        "model_name": request.model_name, "embedding_model": request.embedding_model, "state_snapshot": _json(snapshot.model_dump(mode="json")),
        "created_at": now, "updated_at": now,
    })
    record_audit_event(session, action="AGENT_RUN_CREATED", resource_type="agent_run", resource_id=run_id, actor_user_id=user.user_id, after_state={"agent_type": request.agent_type, "status": "PENDING"}, commit=True)
    return get_agent_run(session, run_id)  # type: ignore[return-value]


def _run_row(session: Session, run_id: str) -> Any | None:
    return session.execute(text("SELECT * FROM agent_run WHERE run_id=:run_id"), {"run_id": run_id}).mappings().one_or_none()


def get_agent_run(session: Session, run_id: str) -> AgentRunDetail | None:
    row = _run_row(session, run_id)
    if row is None:
        return None
    tool_rows = session.execute(text("SELECT * FROM tool_call WHERE run_id=:run_id ORDER BY sequence_no"), {"run_id": run_id}).mappings().all()
    event_rows = session.execute(text("SELECT * FROM agent_run_event WHERE run_id=:run_id ORDER BY sequence_no"), {"run_id": run_id}).mappings().all()
    from app.schemas.agents import AgentRunEventResponse, ToolCallRecordResponse

    tools = [ToolCallRecordResponse(
        id=int(item["id"]), run_id=item["run_id"], sequence_no=int(item["sequence_no"]), tool_name=item["tool_name"],
        permission_code=item["permission_code"], risk_level=item["risk_level"], idempotency_key=item["idempotency_key"],
        input_summary=_decode(item["input_summary"]), output_summary=_decode(item["output_summary"]), status=item["status"],
        error_code=item["error_code"], retryable=bool(item["retryable"]), duration_ms=item["duration_ms"], started_at=item["started_at"], finished_at=item["finished_at"],
    ) for item in tool_rows]
    events = [AgentRunEventResponse(
        id=int(item["id"]), run_id=item["run_id"], sequence_no=int(item["sequence_no"]), event_type=item["event_type"], status=item["status"],
        provider=item["provider"], model_name=item["model_name"], confirmation_type=item["confirmation_type"], input_summary=_decode(item["input_summary"]),
        output_summary=_decode(item["output_summary"]), error_code=item["error_code"], retryable=bool(item["retryable"]), duration_ms=item["duration_ms"],
        actor_user_id=item["actor_user_id"], started_at=item["started_at"], finished_at=item["finished_at"],
    ) for item in event_rows]
    return AgentRunDetail(
        **_summary(row).model_dump(), input_payload=_decode(row["input_payload"]), business_scope=_decode(row["business_scope"]),
        evidence_summary=_decode(row["evidence_summary"]), state_snapshot=_decode(row["state_snapshot"]), tool_calls=tools, events=events,
    )


def list_agent_runs(session: Session, *, requested_by: int | None = None, agent_type: str | None = None) -> AgentRunListResponse:
    conditions: list[str] = []
    params: dict[str, Any] = {}
    if requested_by is not None:
        conditions.append("requested_by=:requested_by")
        params["requested_by"] = requested_by
    if agent_type:
        conditions.append("agent_type=:agent_type")
        params["agent_type"] = agent_type
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    rows = session.execute(text(f"SELECT * FROM agent_run{where} ORDER BY created_at DESC LIMIT 200"), params).mappings().all()
    return AgentRunListResponse(items=[_summary(row) for row in rows])


def transition_agent_run(session: Session, user: UserContext, run_id: str, *, status: str, current_stage: str, stop_reason: str | None = None, confirmation_status: str = "NOT_REQUIRED", state_patch: dict[str, Any] | None = None) -> AgentRunDetail:
    row = _run_row(session, run_id)
    if row is None:
        raise LookupError("agent run not found")
    current = row["status"]
    if status not in ALLOWED_TRANSITIONS.get(current, set()):
        raise AppError("AGENT_INVALID_TRANSITION", f"不允许从 {current} 转换到 {status}", status_code=409)
    snapshot = AgentStateSnapshot.model_validate(_decode(row["state_snapshot"]))
    patch = dict(state_patch or {})
    patch.update({"status": status, "current_stage": current_stage, "stop_reason": stop_reason, "confirmation_status": confirmation_status, "state_version": snapshot.state_version + 1})
    snapshot = snapshot.model_copy(update=patch)
    now = _now()
    finished_at = now if status in TERMINAL_STATUSES else None
    started_at = now if status == "RUNNING" and row["started_at"] is None else row["started_at"]
    session.execute(text("""UPDATE agent_run SET status=:status, stop_reason=:stop_reason, confirmation_status=:confirmation_status,
        state_snapshot=:state_snapshot, started_at=:started_at, finished_at=:finished_at, updated_at=:updated_at WHERE run_id=:run_id"""), {
        "status": status, "stop_reason": stop_reason, "confirmation_status": confirmation_status, "state_snapshot": _json(snapshot.model_dump(mode="json")),
        "started_at": started_at, "finished_at": finished_at, "updated_at": now, "run_id": run_id,
    })
    record_audit_event(session, action="AGENT_RUN_STATE_CHANGED", resource_type="agent_run", resource_id=run_id, actor_user_id=user.user_id, after_state={"status": status, "stop_reason": stop_reason, "stage": current_stage}, commit=True)
    return get_agent_run(session, run_id)  # type: ignore[return-value]


def start_tool_call(session: Session, user: UserContext, run_id: str, contract: ToolContract, *, input_summary: dict[str, Any] | None = None, idempotency_key: str | None = None) -> tuple[int, bool]:
    if contract.idempotency_required and not idempotency_key:
        raise AppError("IDEMPOTENCY_KEY_REQUIRED", "该工具必须提供幂等键", status_code=400)
    if idempotency_key:
        existing = session.execute(text("SELECT id FROM tool_call WHERE idempotency_key=:idempotency_key"), {"idempotency_key": idempotency_key}).scalar_one_or_none()
        if existing is not None:
            return int(existing), True
    sequence = int(session.execute(text("SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM tool_call WHERE run_id=:run_id"), {"run_id": run_id}).scalar_one())
    now = _now()
    session.execute(text("""INSERT INTO tool_call
        (run_id, sequence_no, tool_name, permission_code, risk_level, idempotency_key, input_summary, status, started_at, created_at)
        VALUES (:run_id, :sequence_no, :tool_name, :permission_code, :risk_level, :idempotency_key, :input_summary, 'RUNNING', :started_at, :created_at)"""), {
        "run_id": run_id, "sequence_no": sequence, "tool_name": contract.name, "permission_code": contract.permission_code,
        "risk_level": contract.risk_level, "idempotency_key": idempotency_key, "input_summary": _json(input_summary or {}), "started_at": now, "created_at": now,
    })
    call_id = int(session.execute(text("SELECT LAST_INSERT_ID()")).scalar_one())
    session.commit()
    return call_id, False


def finish_tool_call(session: Session, call_id: int, *, status: str, output_summary: dict[str, Any] | None = None, error_code: str | None = None, retryable: bool = False, duration_ms: int | None = None) -> None:
    session.execute(text("""UPDATE tool_call SET status=:status, output_summary=:output_summary, error_code=:error_code,
        retryable=:retryable, duration_ms=:duration_ms, finished_at=:finished_at WHERE id=:id"""), {
        "status": status, "output_summary": _json(output_summary or {}), "error_code": error_code, "retryable": retryable,
        "duration_ms": duration_ms, "finished_at": _now(), "id": call_id,
    })
    session.commit()
    record_sample("tool_call", float(duration_ms or 0), "error" if status in {"FAILED", "ERROR"} else "success")


def record_agent_event(session: Session, record: ModelCallRecord | ConfirmationRecord, *, event_type: str, status: str, actor_user_id: int | None = None) -> int:
    run_id = record.run_id
    sequence = int(session.execute(text("SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM agent_run_event WHERE run_id=:run_id"), {"run_id": run_id}).scalar_one())
    if isinstance(record, ModelCallRecord):
        provider, model_name, confirmation_type = record.provider, record.model_name, None
        input_summary, output_summary = record.input_summary, record.output_summary
        error_code, retryable, duration_ms = record.error_code, record.retryable, record.duration_ms
    else:
        provider, model_name, confirmation_type = None, None, record.confirmation_type
        input_summary, output_summary = {"comment": record.comment}, {}
        error_code, retryable, duration_ms = None, False, None
    now = _now()
    session.execute(text("""INSERT INTO agent_run_event
        (run_id, sequence_no, event_type, status, provider, model_name, confirmation_type, input_summary, output_summary, error_code, retryable, duration_ms, actor_user_id, started_at, finished_at, created_at)
        VALUES (:run_id, :sequence_no, :event_type, :status, :provider, :model_name, :confirmation_type, :input_summary, :output_summary, :error_code, :retryable, :duration_ms, :actor_user_id, :started_at, :finished_at, :created_at)"""), {
        "run_id": run_id, "sequence_no": sequence, "event_type": event_type, "status": status, "provider": provider, "model_name": model_name,
        "confirmation_type": confirmation_type, "input_summary": _json(input_summary), "output_summary": _json(output_summary), "error_code": error_code,
        "retryable": retryable, "duration_ms": duration_ms, "actor_user_id": actor_user_id, "started_at": now, "finished_at": now, "created_at": now,
    })
    event_id = int(session.execute(text("SELECT LAST_INSERT_ID()")).scalar_one())
    session.commit()
    if isinstance(record, ModelCallRecord):
        component = {
            "EMBEDDING_CALL": "embedding",
            "MODEL_CALL": "model",
            "RAG_SEARCH": "rag_search",
            "DETERMINISTIC_CALCULATION": "deterministic",
        }.get(event_type, "agent_event")
        record_sample(component, float(record.duration_ms or 0), "error" if status in {"FAILED", "ERROR"} else "success")
    return event_id
