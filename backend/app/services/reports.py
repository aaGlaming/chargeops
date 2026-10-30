"""Decision report persistence, confirmation and export services."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from json import dumps
from uuid import uuid4
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agents.contracts import ConfirmationRecord
from app.config import Settings
from app.errors import AppError
from app.schemas.reports import ReportDetail, ReportListResponse, ReportSummary
from app.services.agent_runs import get_agent_run, record_agent_event
from app.services.auth import UserContext, record_audit_event


REPORT_TITLES = {
    "coverage_gap": "覆盖缺口决策报告",
    "competition": "竞争分析决策报告",
    "site_selection": "候选选址决策报告",
    "expansion": "站点扩容决策报告",
    "policy_matching": "政策与补贴匹配决策报告",
}


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _decode(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value if value is not None else default


def _calculation(snapshot: dict[str, Any]) -> dict[str, Any]:
    results = snapshot.get("calculation_results") or {}
    if not isinstance(results, dict):
        return {}
    value = next(iter(results.values()), {})
    return value if isinstance(value, dict) else {}


def _batch_ids(value: Any) -> list[int]:
    found: set[int] = set()
    if isinstance(value, dict):
        if value.get("import_batch_id") is not None:
            try:
                found.add(int(value["import_batch_id"]))
            except (TypeError, ValueError):
                pass
        for item in value.values():
            found.update(_batch_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_batch_ids(item))
    return sorted(found)


def _needs_confirmation(agent_type: str, calculation: dict[str, Any]) -> tuple[bool, str | None]:
    if agent_type == "expansion":
        return True, "expansion_publish"
    if agent_type == "policy_matching":
        return True, "subsidy_application"
    if agent_type == "site_selection":
        ranked = calculation.get("ranked_candidates") or []
        first = ranked[0] if ranked and isinstance(ranked[0], dict) else {}
        if first.get("recommendation_grade") == "A" or float(first.get("total_score") or 0) >= 80:
            return True, "site_recommendation"
    return False, None


def _report_payload(run: Any, *, title: str | None = None) -> dict[str, Any]:
    snapshot = run.state_snapshot if hasattr(run, "state_snapshot") else {}
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    calculation = _calculation(snapshot)
    agent_type = str(run.agent_type)
    needs_confirmation, confirmation_type = _needs_confirmation(agent_type, calculation)
    if run.status == "COMPLETED" and agent_type == "expansion":
        status = "APPROVED"
    elif needs_confirmation and run.status in {"COMPLETED", "WAITING_CONFIRMATION"}:
        status = "WAITING_CONFIRMATION"
    else:
        status = "DRAFT"
    return {
        "report_id": str(uuid4()),
        "run_id": run.run_id,
        "report_type": agent_type,
        "title": title or REPORT_TITLES.get(agent_type, "ChargeOps 决策报告"),
        "status": status,
        "conclusion": (snapshot.get("conclusion") or {}).get("conclusion") if isinstance(snapshot.get("conclusion"), dict) else None,
        "input_snapshot": {"input_payload": run.input_payload, "business_scope": run.business_scope, "agent_type": agent_type},
        "calculation_summary": calculation,
        "business_data": snapshot.get("tool_results") if isinstance(snapshot.get("tool_results"), dict) else {},
        "rag_evidence": snapshot.get("evidence") if isinstance(snapshot.get("evidence"), list) else [],
        "data_version": run.data_version,
        "data_batch_ids": _batch_ids(snapshot.get("tool_results") or {}),
        "document_versions": sorted({str(item.get("version")) for item in (snapshot.get("evidence") or []) if isinstance(item, dict) and item.get("version")}),
        "prompt_version": run.prompt_version,
        "model_version": run.model_name,
        "embedding_model": run.embedding_model,
        "calculation_rule_version": calculation.get("scoring_rule_version") or calculation.get("rule_version"),
        "confirmation_type": confirmation_type,
    }


def _summary(row: Any) -> ReportSummary:
    return ReportSummary(
        report_id=row["report_id"], run_id=row["run_id"], report_type=row["report_type"], title=row["title"], status=row["status"],
        data_version=row["data_version"], calculation_rule_version=row["calculation_rule_version"], confirmed_by=row["confirmed_by"],
        confirmed_at=row["confirmed_at"], created_by=int(row["created_by"]), created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _detail(row: Any) -> ReportDetail:
    return ReportDetail(
        **_summary(row).model_dump(), conclusion=row["conclusion"], input_snapshot=_decode(row["input_snapshot"], {}),
        calculation_summary=_decode(row["calculation_summary"], {}), business_data=_decode(row["business_data"], {}),
        rag_evidence=_decode(row["rag_evidence"], []), prompt_version=row["prompt_version"], model_version=row["model_version"],
        embedding_model=row["embedding_model"], data_batch_ids=_decode(row["data_batch_ids"], []), document_versions=_decode(row["document_versions"], []),
        confirmation_type=row["confirmation_type"], confirmation_comment=row["confirmation_comment"],
        rejection_reason=row["rejection_reason"], archived_at=row["archived_at"],
    )


def _row(session: Session, report_id: str) -> Any | None:
    return session.execute(text("SELECT * FROM agent_report WHERE report_id=:report_id"), {"report_id": report_id}).mappings().one_or_none()


def get_report(session: Session, report_id: str) -> ReportDetail | None:
    row = _row(session, report_id)
    return _detail(row) if row else None


def list_reports(session: Session, *, created_by: int | None = None, report_type: str | None = None, status: str | None = None) -> ReportListResponse:
    conditions: list[str] = []
    params: dict[str, Any] = {}
    for value, key in ((created_by, "created_by"), (report_type, "report_type"), (status, "status")):
        if value is not None:
            conditions.append(f"{key}=:{key}")
            params[key] = value
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = session.execute(text(f"SELECT * FROM agent_report{where} ORDER BY created_at DESC LIMIT 200"), params).mappings().all()
    return ReportListResponse(items=[_summary(row) for row in rows])


def create_report(session: Session, user: UserContext, *, run_id: str, title: str | None = None) -> ReportDetail:
    run = get_agent_run(session, run_id)
    if run is None:
        raise AppError("AGENT_RUN_NOT_FOUND", "Agent 运行不存在", status_code=404, details={"run_id": run_id})
    if run.requested_by != user.user_id and not ({"SYSTEM_ADMIN", "AUDITOR"} & set(user.role_codes)):
        raise AppError("FORBIDDEN", "无权创建该运行的报告", status_code=403)
    existing = session.execute(text("SELECT * FROM agent_report WHERE run_id=:run_id"), {"run_id": run_id}).mappings().one_or_none()
    if existing:
        return _detail(existing)
    payload = _report_payload(run, title=title)
    now = _now()
    session.execute(text("""INSERT INTO agent_report
        (report_id, run_id, report_type, title, status, conclusion, input_snapshot, calculation_summary,
         business_data, rag_evidence, data_version, prompt_version, model_version, embedding_model,
         data_batch_ids, document_versions, calculation_rule_version, confirmation_type, created_by, created_at, updated_at)
        VALUES (:report_id, :run_id, :report_type, :title, :status, :conclusion, :input_snapshot, :calculation_summary,
         :business_data, :rag_evidence, :data_version, :prompt_version, :model_version, :embedding_model,
         :data_batch_ids, :document_versions, :calculation_rule_version, :confirmation_type, :created_by, :created_at, :updated_at)"""), {
        **payload,
        "input_snapshot": dumps(payload["input_snapshot"], ensure_ascii=False, default=str),
        "calculation_summary": dumps(payload["calculation_summary"], ensure_ascii=False, default=str),
        "business_data": dumps(payload["business_data"], ensure_ascii=False, default=str),
        "rag_evidence": dumps(payload["rag_evidence"], ensure_ascii=False, default=str),
        "data_batch_ids": dumps(payload["data_batch_ids"], ensure_ascii=False, default=str),
        "document_versions": dumps(payload["document_versions"], ensure_ascii=False, default=str),
        "created_by": user.user_id, "created_at": now, "updated_at": now,
    })
    record_audit_event(session, action="REPORT_CREATED", resource_type="agent_report", resource_id=payload["report_id"], actor_user_id=user.user_id, after_state={"run_id": run_id, "status": payload["status"]})
    session.commit()
    return get_report(session, payload["report_id"])  # type: ignore[return-value]


def _authorize_report(session: Session, user: UserContext, row: Any) -> None:
    if int(row["created_by"]) != user.user_id and not ({"SYSTEM_ADMIN", "AUDITOR"} & set(user.role_codes)):
        raise AppError("FORBIDDEN", "无权访问该报告", status_code=403)


def confirm_report(session: Session, settings: Settings, user: UserContext, report_id: str, *, decision: str, comment: str) -> ReportDetail:
    row = _row(session, report_id)
    if row is None:
        raise AppError("REPORT_NOT_FOUND", "报告不存在", status_code=404)
    _authorize_report(session, user, row)
    if row["status"] != "WAITING_CONFIRMATION":
        raise AppError("REPORT_CONFIRMATION_NOT_PENDING", "报告当前不在待确认状态", status_code=409, details={"status": row["status"]})
    before = {"status": row["status"], "confirmation_comment": row["confirmation_comment"], "rejection_reason": row["rejection_reason"]}
    run = get_agent_run(session, row["run_id"])
    if run is not None and row["report_type"] == "expansion" and run.status == "WAITING_CONFIRMATION":
        from app.agents.supervisor import confirm_agent_run

        confirm_agent_run(session, settings, user, row["run_id"], decision=decision, comment=comment)
        run = get_agent_run(session, row["run_id"])
    status = "APPROVED" if decision == "APPROVE" else "REJECTED"
    now = _now()
    if run is not None and row["report_type"] == "expansion":
        refreshed = _report_payload(run, title=row["title"])
        session.execute(text("""UPDATE agent_report SET conclusion=:conclusion, input_snapshot=:input_snapshot,
            calculation_summary=:calculation_summary, business_data=:business_data, rag_evidence=:rag_evidence,
            data_version=:data_version, data_batch_ids=:data_batch_ids, document_versions=:document_versions,
            prompt_version=:prompt_version, model_version=:model_version,
            embedding_model=:embedding_model, calculation_rule_version=:calculation_rule_version WHERE report_id=:report_id"""), {
            "conclusion": refreshed["conclusion"], "input_snapshot": dumps(refreshed["input_snapshot"], ensure_ascii=False, default=str),
            "calculation_summary": dumps(refreshed["calculation_summary"], ensure_ascii=False, default=str),
            "business_data": dumps(refreshed["business_data"], ensure_ascii=False, default=str),
            "rag_evidence": dumps(refreshed["rag_evidence"], ensure_ascii=False, default=str), "data_version": refreshed["data_version"],
            "data_batch_ids": dumps(refreshed["data_batch_ids"], ensure_ascii=False, default=str),
            "document_versions": dumps(refreshed["document_versions"], ensure_ascii=False, default=str),
            "prompt_version": refreshed["prompt_version"], "model_version": refreshed["model_version"], "embedding_model": refreshed["embedding_model"],
            "calculation_rule_version": refreshed["calculation_rule_version"], "report_id": report_id,
        })
    session.execute(text("""UPDATE agent_report SET status=:status, confirmed_by=:confirmed_by, confirmed_at=:confirmed_at,
        confirmation_comment=:confirmation_comment, rejection_reason=:rejection_reason, updated_at=:updated_at WHERE report_id=:report_id"""), {
        "status": status, "confirmed_by": user.user_id, "confirmed_at": now, "confirmation_comment": comment,
        "rejection_reason": comment if decision == "REJECT" else None, "updated_at": now, "report_id": report_id,
    })
    if run is not None and row["report_type"] != "expansion":
        record_agent_event(session, ConfirmationRecord(run_id=row["run_id"], confirmation_type=row["confirmation_type"] or "report", status=status, requested_by=run.requested_by, decided_by=user.user_id, comment=comment, requested_at=run.created_at, decided_at=now), event_type="HUMAN_CONFIRMATION", status=status, actor_user_id=user.user_id)
    record_audit_event(session, action="REPORT_CONFIRMED", resource_type="agent_report", resource_id=report_id, actor_user_id=user.user_id, before_state=before, after_state={"status": status, "comment": comment})
    session.commit()
    return get_report(session, report_id)  # type: ignore[return-value]


def archive_report(session: Session, user: UserContext, report_id: str) -> ReportDetail:
    row = _row(session, report_id)
    if row is None:
        raise AppError("REPORT_NOT_FOUND", "报告不存在", status_code=404)
    _authorize_report(session, user, row)
    if row["status"] not in {"APPROVED", "REJECTED", "DRAFT"}:
        raise AppError("REPORT_ARCHIVE_NOT_ALLOWED", "当前报告状态不允许归档", status_code=409)
    now = _now()
    session.execute(text("UPDATE agent_report SET status='ARCHIVED', archived_at=:archived_at, updated_at=:updated_at WHERE report_id=:report_id"), {"archived_at": now, "updated_at": now, "report_id": report_id})
    record_audit_event(session, action="REPORT_ARCHIVED", resource_type="agent_report", resource_id=report_id, actor_user_id=user.user_id, after_state={"status": "ARCHIVED"})
    session.commit()
    return get_report(session, report_id)  # type: ignore[return-value]


def render_markdown(report: ReportDetail) -> str:
    lines = [f"# {report.title}", "", f"- 报告 ID：`{report.report_id}`", f"- 运行 ID：`{report.run_id}`", f"- 类型：`{report.report_type}`", f"- 状态：`{report.status}`", f"- 数据版本：`{report.data_version or '未指定'}`", f"- 数据批次：`{', '.join(str(item) for item in report.data_batch_ids) or '未指定'}`", f"- 文档版本：`{', '.join(report.document_versions) or '未指定'}`", f"- 计算规则版本：`{report.calculation_rule_version or '未指定'}`", "", "## 结论", "", report.conclusion or "暂无结论", "", "## 计算结果", "", "```json", dumps(report.calculation_summary, ensure_ascii=False, indent=2, default=str), "```", "", "## MySQL 业务数据", "", "```json", dumps(report.business_data, ensure_ascii=False, indent=2, default=str), "```", "", "## RAG 原文证据", ""]
    if report.rag_evidence:
        for index, evidence in enumerate(report.rag_evidence, start=1):
            lines.extend([f"### 证据 {index}：{evidence.get('title') or evidence.get('evidence_id') or '未命名'}", "", str(evidence.get("content") or ""), ""])
    else:
        lines.append("暂无已校验证据。\n")
    lines.extend(["## 人工确认", "", f"- 确认人：`{report.confirmed_by or '未确认'}`", f"- 确认时间：`{report.confirmed_at or '未确认'}`", f"- 意见：{report.confirmation_comment or '暂无'}", ""])
    return "\n".join(lines)


def report_json(report: ReportDetail) -> dict[str, Any]:
    return report.model_dump(mode="json")
