"""Unified execution layer for registered Agent tools.

The executor is deliberately the only entry point used by the Supervisor for
business tools.  It performs the common contract checks first, then dispatches
to a deterministic implementation and persists a bounded execution trace.
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agents.registry import get_tool_contract
from app.agents.coverage_gap import analyze_coverage_gap
from app.agents.competition import analyze_competition
from app.agents.site_selection import analyze_site_selection
from app.agents.expansion import analyze_expansion
from app.config import Settings
from app.errors import AppError
from app.schemas.agents import ToolExecuteResponse
from app.schemas.catalog import ConnectorQuery, StationQuery
from app.schemas.operations import FaultQuery, MetricQuery
from app.schemas.rag import RagSearchRequest
from app.services.agent_runs import finish_tool_call, start_tool_call
from app.services.auth import UserContext, record_audit_event
from app.services.catalog import list_connectors, list_operators, list_regions, list_stations
from app.services.operations import list_candidates, list_faults, list_metrics
from app.services.rag_search import EmbeddingServiceError, search_rag
from app.tools.authorization import authorize_tool, ensure_idempotency_key


def _json_value(value: Any) -> Any:
    """Convert Pydantic/date/decimal values into JSON-safe values."""

    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif isinstance(value, (list, tuple)):
        value = [_json_value(item) for item in value]
    elif isinstance(value, dict):
        value = {key: _json_value(item) for key, item in value.items()}
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _bounded(value: Any, *, depth: int = 0, max_items: int = 100, max_text: int = 4000) -> Any:
    """Keep audit/tool_call payloads useful without allowing unbounded JSON."""

    if depth > 5:
        return "[truncated]"
    if isinstance(value, dict):
        items = list(value.items())[:max_items]
        result = {str(key): _bounded(item, depth=depth + 1, max_items=max_items, max_text=max_text) for key, item in items}
        if len(value) > max_items:
            result["_truncated"] = True
        return result
    if isinstance(value, (list, tuple)):
        result = [_bounded(item, depth=depth + 1, max_items=max_items, max_text=max_text) for item in list(value)[:max_items]]
        if len(value) > max_items:
            result.append("[truncated]")
        return result
    if isinstance(value, str) and len(value) > max_text:
        return value[:max_text] + "...[truncated]"
    return value


def _decode(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return value if isinstance(value, dict) else {}


def _run(session: Session, run_id: str) -> Any:
    row = session.execute(text("SELECT * FROM agent_run WHERE run_id=:run_id"), {"run_id": run_id}).mappings().one_or_none()
    if row is None:
        raise AppError("AGENT_RUN_NOT_FOUND", "Agent 运行不存在", status_code=404, details={"run_id": run_id})
    return row


def _region_code(params: dict[str, Any]) -> str | None:
    scope = params.get("business_scope")
    return params.get("region_code") or (scope.get("region_code") if isinstance(scope, dict) else None)


def _page(items: list[Any], total: int, params: dict[str, Any]) -> dict[str, Any]:
    page = int(params.get("page", 1))
    page_size = int(params.get("page_size", max(1, len(items))))
    return {"page": page, "page_size": page_size, "total": total, "has_next": page * page_size < total}


def _existing_call(session: Session, call_id: int, run_id: str) -> ToolExecuteResponse:
    row = session.execute(text("SELECT * FROM tool_call WHERE id=:id"), {"id": call_id}).mappings().one_or_none()
    if row is None or row["run_id"] != run_id:
        raise AppError("IDEMPOTENCY_KEY_CONFLICT", "幂等键已被其他 Agent 运行使用", status_code=409)
    output = _decode(row["output_summary"])
    if row["status"] == "RUNNING":
        raise AppError("TOOL_ALREADY_RUNNING", "相同幂等键的工具仍在执行，请稍后重试", status_code=409, retryable=True)
    error = output.get("_error") if row["status"] == "FAILED" else None
    result = output.get("_result", output)
    return ToolExecuteResponse(
        run_id=run_id,
        tool_name=row["tool_name"],
        tool_call_id=int(row["id"]),
        status=row["status"],
        result=result if isinstance(result, dict) else {"value": result},
        error=error if isinstance(error, dict) else None,
        duration_ms=row["duration_ms"],
    )


def _update_snapshot(session: Session, run_id: str, *, tool_name: str, result: dict[str, Any], error: dict[str, Any] | None = None) -> None:
    row = session.execute(text("SELECT state_snapshot, evidence_summary FROM agent_run WHERE run_id=:run_id"), {"run_id": run_id}).mappings().one_or_none()
    if row is None:
        return
    snapshot = _decode(row["state_snapshot"])
    tool_results = snapshot.setdefault("tool_results", {})
    tool_results[tool_name] = _bounded(result)
    snapshot["tool_call_count"] = int(snapshot.get("tool_call_count", 0)) + 1
    if error:
        errors = snapshot.setdefault("errors", [])
        errors.append(error)
    evidence = _decode(row["evidence_summary"])
    if tool_name == "rag.search" and isinstance(result.get("hits"), list):
        evidence["last_rag_hit_count"] = len(result["hits"])
        evidence["last_rag_run_id"] = result.get("run_id")
    session.execute(text("UPDATE agent_run SET state_snapshot=:state_snapshot, evidence_summary=:evidence_summary, updated_at=:updated_at WHERE run_id=:run_id"), {
        "state_snapshot": json.dumps(_bounded(snapshot), ensure_ascii=False, default=str),
        "evidence_summary": json.dumps(_bounded(evidence), ensure_ascii=False, default=str),
        "updated_at": datetime.now(timezone.utc).replace(tzinfo=None),
        "run_id": run_id,
    })
    session.commit()


def _coverage(params: dict[str, Any]) -> dict[str, Any]:
    stations = params.get("stations") or params.get("items") or []
    connectors = params.get("connectors") or []
    metrics = params.get("metrics") or []
    if not isinstance(stations, list) or not isinstance(connectors, list) or not isinstance(metrics, list):
        raise ValueError("stations, connectors and metrics must be arrays")
    return analyze_coverage_gap(
        params,
        region=params.get("region") if isinstance(params.get("region"), dict) else None,
        stations=stations,
        connectors=connectors,
        metrics=metrics,
    )


def _competition(params: dict[str, Any]) -> dict[str, Any]:
    stations = params.get("nearby_stations") or params.get("stations") or []
    connectors = params.get("connectors") or []
    if not isinstance(stations, list) or not isinstance(connectors, list):
        raise ValueError("nearby_stations and connectors must be arrays")
    return analyze_competition(params, stations=stations, connectors=connectors)


def _site_score(params: dict[str, Any]) -> dict[str, Any]:
    candidates = params.get("candidates") or params.get("items") or []
    stations = params.get("stations") or []
    regions = params.get("regions") or []
    if not isinstance(candidates, list) or not isinstance(stations, list) or not isinstance(regions, list):
        raise ValueError("candidates, stations and regions must be arrays")
    return analyze_site_selection(params, candidates=candidates, regions=regions, stations=stations)


def _expansion(params: dict[str, Any]) -> dict[str, Any]:
    stations = params.get("stations") or params.get("metrics") or []
    connectors = params.get("connectors") or []
    metrics = params.get("metrics") or []
    faults = params.get("faults") or []
    if not all(isinstance(value, list) for value in (stations, connectors, metrics, faults)):
        raise ValueError("stations, connectors, metrics and faults must be arrays")
    return analyze_expansion(params, stations=stations, connectors=connectors, metrics=metrics, faults=faults)


def _policy_match(params: dict[str, Any]) -> dict[str, Any]:
    policies = params.get("policies") or []
    subject = params.get("subject") or {}
    matched, missing = [], []
    for policy in policies:
        key = policy.get("condition_key")
        operator = str(policy.get("condition_operator", "EQ")).upper()
        expected = policy.get("condition_value")
        actual = subject.get(key) if key else None
        ok = False
        if actual is not None:
            if operator in {"EQ", "="}:
                ok = str(actual).lower() == str(expected).lower()
            elif operator in {"GTE", ">="}:
                ok = float(actual) >= float(expected)
            elif operator in {"LTE", "<="}:
                ok = float(actual) <= float(expected)
            elif operator == "IN":
                ok = str(actual) in {part.strip() for part in str(expected).split(",")}
        if ok:
            matched.append(policy)
        else:
            missing.append(str(key or "condition"))
    materials = []
    for policy in matched:
        values = policy.get("required_materials") or []
        materials.extend(values if isinstance(values, list) else [part.strip() for part in str(values).split(",") if part.strip()])
    return {"status": "COMPLETED", "matched_policies": matched, "missing_conditions": sorted(set(missing)), "required_materials": sorted(set(materials))}


def _verify_evidence(session: Session, params: dict[str, Any]) -> dict[str, Any]:
    evidence = params.get("evidence") or params.get("hits") or []
    if not isinstance(evidence, list):
        raise ValueError("evidence must be an array")
    valid, invalid = [], []
    for item in evidence:
        if not isinstance(item, dict):
            invalid.append({"reason": "evidence item must be an object"})
            continue
        chunk_id = item.get("chunk_id") or item.get("chunk_key")
        row = session.execute(text("""SELECT c.chunk_key, c.document_id, c.start_char, c.end_char, c.content,
            d.deleted_at FROM rag_chunk c JOIN rag_document d ON d.id=c.document_id
            WHERE c.chunk_key=:chunk_id"""), {"chunk_id": chunk_id}).mappings().one_or_none() if chunk_id else None
        issues = []
        if row is None or row["deleted_at"] is not None:
            issues.append("chunk_not_found")
        else:
            if item.get("document_id") is not None and int(item["document_id"]) != int(row["document_id"]):
                issues.append("document_mismatch")
            if item.get("start_char") is not None and int(item["start_char"]) != int(row["start_char"]):
                issues.append("start_char_mismatch")
            if item.get("end_char") is not None and int(item["end_char"]) != int(row["end_char"]):
                issues.append("end_char_mismatch")
            if item.get("content") and str(item["content"]).strip() not in str(row["content"]):
                issues.append("content_mismatch")
        if issues:
            invalid.append({"chunk_id": chunk_id, "issues": issues})
        else:
            valid.append({"chunk_id": chunk_id, "document_id": int(row["document_id"]), "start_char": int(row["start_char"]), "end_char": int(row["end_char"])})
    return {"status": "COMPLETED" if not invalid else "EVIDENCE_INSUFFICIENT", "valid_count": len(valid), "invalid_count": len(invalid), "valid": valid, "invalid": invalid}


def _dispatch(session: Session, settings: Settings, user: UserContext, run_id: str, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "region.query":
        items, total = list_regions(session, region_code=params.get("region_code"), data_version=params.get("data_version"), page=int(params.get("page", 1)), page_size=int(params.get("page_size", 50)))
        serialized = [_json_value(item) for item in items]
        if params.get("include_boundary") and serialized:
            from app.services.catalog import table_columns

            columns = table_columns(session, "region")
            boundary = "r.`boundary_geojson`" if columns.has("boundary_geojson") else "NULL"
            region_type = "r.`region_type`" if columns.has("region_type") else "NULL"
            country_code = "r.`country_code`" if columns.has("country_code") else "NULL"
            version_clause = " AND r.data_version=:data_version" if params.get("data_version") else ""
            boundary_params = {"region_code": params.get("region_code"), "data_version": params.get("data_version")}
            row = session.execute(
                text(f"SELECT {boundary} AS boundary_geojson, {region_type} AS region_type, {country_code} AS country_code FROM region r WHERE r.region_code=:region_code{version_clause} ORDER BY r.data_version DESC LIMIT 1"),
                boundary_params,
            ).mappings().one_or_none()
            if row:
                serialized[0].update({"boundary_geojson": _json_value(row["boundary_geojson"]), "region_type": row["region_type"], "country_code": row["country_code"]})
        return {"items": serialized, "page": _page(items, total, params)}
    if tool_name == "operator.query":
        items, total = list_operators(session, operator_name=params.get("operator_name"), page=int(params.get("page", 1)), page_size=int(params.get("page_size", 50)))
        return {"items": _json_value(items), "page": _page(items, total, params)}
    if tool_name == "station.query":
        query = StationQuery.model_validate(params)
        if query.all_pages:
            collected: list[dict[str, Any]] = []
            total = 0
            page = 1
            while len(collected) < query.max_rows:
                current = query.model_copy(update={"page": page, "all_pages": False})
                batch, total = list_stations(session, current)
                collected.extend(batch)
                if not batch or page * current.page_size >= total:
                    break
                page += 1
            collected = collected[: query.max_rows]
            return {"items": _json_value(collected), "page": {"page": 1, "page_size": len(collected), "total": total, "has_next": len(collected) < total}}
        items, total = list_stations(session, query)
        return {"items": _json_value(items), "page": _page(items, total, params)}
    if tool_name == "connector.query":
        query = ConnectorQuery.model_validate(params)
        if query.all_pages:
            collected: list[dict[str, Any]] = []
            total = 0
            page = 1
            while len(collected) < query.max_rows:
                current = query.model_copy(update={"page": page, "all_pages": False})
                batch, total = list_connectors(session, current)
                collected.extend(batch)
                if not batch or page * current.page_size >= total:
                    break
                page += 1
            collected = collected[: query.max_rows]
            return {"items": _json_value(collected), "page": {"page": 1, "page_size": len(collected), "total": total, "has_next": len(collected) < total}}
        items, total = list_connectors(session, query)
        return {"items": _json_value(items), "page": _page(items, total, params)}
    if tool_name == "operation.query":
        query = MetricQuery.model_validate(params)
        if query.all_pages:
            collected: list[dict[str, Any]] = []
            total = 0
            page = 1
            while len(collected) < query.max_rows:
                current = query.model_copy(update={"page": page, "all_pages": False})
                batch, total = list_metrics(session, current)
                collected.extend(batch)
                if not batch or page * current.page_size >= total:
                    break
                page += 1
            collected = collected[: query.max_rows]
            return {"items": _json_value(collected), "page": {"page": 1, "page_size": len(collected), "total": total, "has_next": len(collected) < total}}
        items, total = list_metrics(session, query)
        return {"items": _json_value(items), "page": _page(items, total, params)}
    if tool_name == "fault.query":
        query = FaultQuery.model_validate(params)
        if query.all_pages:
            collected: list[dict[str, Any]] = []
            total = 0
            page = 1
            while len(collected) < query.max_rows:
                current = query.model_copy(update={"page": page, "all_pages": False})
                batch, total = list_faults(session, current)
                collected.extend(batch)
                if not batch or page * current.page_size >= total:
                    break
                page += 1
            collected = collected[: query.max_rows]
            return {"items": _json_value(collected), "page": {"page": 1, "page_size": len(collected), "total": total, "has_next": len(collected) < total}}
        items, total = list_faults(session, query)
        return {"items": _json_value(items), "page": _page(items, total, params)}
    if tool_name == "candidate.query":
        items, total = list_candidates(session, region_code=params.get("region_code"), lifecycle_status=params.get("lifecycle_status"), data_status=params.get("data_status"), source_type=params.get("source_type"), candidate_ids=params.get("candidate_ids"), page=int(params.get("page", 1)), page_size=int(params.get("page_size", 50)))
        return {"items": _json_value(items), "page": _page(items, total, params)}
    if tool_name == "policy.query":
        conditions = ["deleted_at IS NULL"]
        values: dict[str, Any] = {"limit": int(params.get("page_size", 50)), "offset": (int(params.get("page", 1)) - 1) * int(params.get("page_size", 50))}
        if params.get("region_code"):
            conditions.append("region_id IN (SELECT id FROM region WHERE region_code=:region_code)")
            values["region_code"] = params["region_code"]
        if params.get("data_version"):
            conditions.append("data_version=:data_version")
            values["data_version"] = params["data_version"]
        where = " AND ".join(conditions)
        total = int(session.execute(text(f"SELECT COUNT(*) FROM policy_condition WHERE {where}"), values).scalar_one())
        rows = session.execute(text(f"""SELECT id, policy_code, policy_version, title, policy_type,
            applicant_type, condition_key, condition_operator, condition_value, required_materials,
            effective_from, effective_to, application_deadline, source_type, source_url, source_file,
            data_version, import_batch_id FROM policy_condition WHERE {where}
            ORDER BY effective_from DESC, id DESC LIMIT :limit OFFSET :offset"""), values).mappings().all()
        return {"items": _json_value([dict(row) for row in rows]), "page": _page(list(rows), total, params)}
    if tool_name == "rag.search":
        request = RagSearchRequest.model_validate(params)
        return _json_value(search_rag(session, settings, user, request).model_dump(mode="json"))
    if tool_name == "rag.evidence.verify":
        return _verify_evidence(session, params)
    if tool_name == "coverage.analyze":
        return _coverage(params)
    if tool_name == "competition.analyze":
        return _competition(params)
    if tool_name == "site.score":
        return _site_score(params)
    if tool_name == "expansion.plan":
        return _expansion(params)
    if tool_name == "policy.match":
        return _policy_match(params)
    raise AppError("AGENT_TOOL_NOT_IMPLEMENTED", "工具契约已登记但尚未实现", status_code=501, details={"tool_name": tool_name})


def _write_analysis(session: Session, run_id: str, params: dict[str, Any], run: Any) -> dict[str, Any]:
    result = params.get("result") or {key: value for key, value in params.items() if key not in {"data_version", "business_scope"}}
    if not isinstance(result, dict):
        raise ValueError("result must be an object")
    snapshot = _decode(run["state_snapshot"])
    snapshot["conclusion"] = _bounded(result)
    snapshot["status"] = result.get("status", snapshot.get("status", "COMPLETED"))
    evidence = result.get("evidence") or []
    session.execute(text("UPDATE agent_run SET evidence_summary=:evidence_summary, state_snapshot=:state_snapshot, updated_at=:updated_at WHERE run_id=:run_id"), {
        "evidence_summary": json.dumps(_bounded({"evidence": evidence, "data_version": params.get("data_version") or run["data_version"]}), ensure_ascii=False, default=str),
        "state_snapshot": json.dumps(_bounded(snapshot), ensure_ascii=False, default=str),
        "updated_at": datetime.now(timezone.utc).replace(tzinfo=None), "run_id": run_id,
    })
    session.commit()
    return {"run_id": run_id, "saved": True, "result": _json_value(result)}


def _write_score(session: Session, run_id: str, params: dict[str, Any], run: Any) -> dict[str, Any]:
    candidate_id = params.get("candidate_site_id") or params.get("candidate_id")
    if not candidate_id:
        raise ValueError("candidate_site_id is required")
    exists = session.execute(text("SELECT COUNT(*) FROM candidate_site WHERE id=:id AND deleted_at IS NULL"), {"id": candidate_id}).scalar_one()
    if not exists:
        raise ValueError("candidate_site_id does not exist")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    data_version = params.get("data_version") or run["data_version"] or date.today().isoformat()
    result = params.get("result") or params
    session.execute(text("""INSERT INTO site_score
        (candidate_site_id, run_id, scoring_rule_version, coverage_score, traffic_score, competition_score,
         construction_score, policy_score, data_confidence_score, total_score, recommendation_grade,
         deduction_reasons, missing_data, evidence, status, source_type, data_version, created_at, updated_at)
        VALUES (:candidate_site_id, :run_id, :scoring_rule_version, :coverage_score, :traffic_score, :competition_score,
         :construction_score, :policy_score, :data_confidence_score, :total_score, :recommendation_grade,
         :deduction_reasons, :missing_data, :evidence, :status, 'agent', :data_version, :created_at, :updated_at)"""), {
        "candidate_site_id": candidate_id, "run_id": run_id, "scoring_rule_version": params.get("scoring_rule_version", "tool-v1"),
        "coverage_score": result.get("coverage_score"), "traffic_score": result.get("traffic_score"), "competition_score": result.get("competition_score"),
        "construction_score": result.get("construction_score"), "policy_score": result.get("policy_score"), "data_confidence_score": result.get("data_confidence_score", result.get("confidence_score")),
        "total_score": result.get("total_score"), "recommendation_grade": result.get("recommendation_grade"),
        "deduction_reasons": json.dumps(result.get("deduction_reasons", []), ensure_ascii=False, default=str), "missing_data": json.dumps(result.get("missing_data", []), ensure_ascii=False, default=str),
        "evidence": json.dumps(result.get("evidence", []), ensure_ascii=False, default=str), "status": result.get("status", "DRAFT"), "data_version": data_version, "created_at": now, "updated_at": now,
    })
    score_id = int(session.execute(text("SELECT LAST_INSERT_ID()")).scalar_one())
    session.commit()
    return {"site_score_id": score_id, "candidate_site_id": int(candidate_id), "run_id": run_id, "status": result.get("status", "DRAFT"), "data_version": data_version}


def _write_expansion(session: Session, run_id: str, params: dict[str, Any], run: Any, idempotency_key: str) -> dict[str, Any]:
    plans = params.get("plans") or []
    if not isinstance(plans, list) or not plans:
        plan = params.get("plan")
        plans = [plan] if isinstance(plan, dict) else []
    if not plans:
        raise ValueError("plans must contain at least one expansion plan")
    # The imported charging_station table predates soft-delete support, so it
    # intentionally has no deleted_at column.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    data_version = params.get("data_version") or run["data_version"] or date.today().isoformat()
    saved: list[dict[str, Any]] = []
    for plan in plans:
        if not isinstance(plan, dict) or not plan.get("station_id"):
            raise ValueError("each expansion plan requires station_id")
        station_id = int(plan["station_id"])
        exists = session.execute(text("SELECT COUNT(*) FROM charging_station WHERE id=:id"), {"id": station_id}).scalar_one()
        if not exists:
            raise ValueError("station_id does not exist")
        external_case_id = params.get("external_case_id") or f"{run_id}:expansion:{station_id}"
        session.execute(text("""INSERT INTO expansion_plan
            (external_case_id, station_id, run_id, existing_fast_connectors, existing_slow_connectors,
             peak_occupancy_rate, fault_count_30d, available_capacity_kw, proposed_fast_connectors,
             proposed_slow_connectors, requested_budget_usd, priority, preconditions, risk_summary, evidence,
             confirmation_status, source_type, data_version, created_at, updated_at)
            VALUES (:external_case_id, :station_id, :run_id, :existing_fast_connectors, :existing_slow_connectors,
             :peak_occupancy_rate, :fault_count_30d, :available_capacity_kw, :proposed_fast_connectors,
             :proposed_slow_connectors, :requested_budget_usd, :priority, :preconditions, :risk_summary, :evidence,
             'WAITING_CONFIRMATION', 'agent', :data_version, :created_at, :updated_at)"""), {
            "external_case_id": external_case_id, "station_id": station_id, "run_id": run_id,
            "existing_fast_connectors": plan.get("existing_fast_connectors"), "existing_slow_connectors": plan.get("existing_slow_connectors"),
            "peak_occupancy_rate": plan.get("peak_occupancy_rate"), "fault_count_30d": plan.get("fault_count_30d"), "available_capacity_kw": plan.get("available_capacity_kw"),
            "proposed_fast_connectors": plan.get("proposed_fast_connectors", 0), "proposed_slow_connectors": plan.get("proposed_slow_connectors", 0), "requested_budget_usd": plan.get("requested_budget_usd", params.get("budget_usd")),
            "priority": plan.get("priority", "MEDIUM"), "preconditions": json.dumps(plan.get("preconditions", []), ensure_ascii=False, default=str), "risk_summary": json.dumps(plan.get("risk_summary", []), ensure_ascii=False, default=str), "evidence": json.dumps(plan.get("evidence", params.get("evidence", [])), ensure_ascii=False, default=str),
            "data_version": data_version, "created_at": now, "updated_at": now,
        })
        plan_id = int(session.execute(text("SELECT LAST_INSERT_ID()" )).scalar_one())
        saved.append({"expansion_plan_id": plan_id, "station_id": station_id})
    session.commit()
    return {"plans": saved, "run_id": run_id, "status": "WAITING_CONFIRMATION", "confirmation_status": "WAITING_CONFIRMATION", "data_version": data_version}


def execute_tool(session: Session, settings: Settings, user: UserContext, run_id: str, tool_name: str, params: dict[str, Any], idempotency_key: str | None = None) -> ToolExecuteResponse:
    contract = get_tool_contract(tool_name)
    if contract is None:
        raise AppError("AGENT_TOOL_NOT_FOUND", "Agent 工具契约不存在", status_code=404, details={"tool_name": tool_name})
    run = _run(session, run_id)
    if run["agent_type"] not in contract.allowed_agent_types:
        raise AppError("AGENT_TOOL_NOT_ALLOWED", "该工具不属于当前 Agent 类型", status_code=403, details={"tool_name": tool_name, "agent_type": run["agent_type"]})
    if run["status"] in {"COMPLETED", "CANCELLED", "BLOCKED"}:
        raise AppError("AGENT_RUN_NOT_EXECUTABLE", "当前 Agent 运行状态不允许执行工具", status_code=409, details={"status": run["status"]})
    expected_version = run["data_version"]
    requested_version = params.get("data_version")
    if expected_version and requested_version and expected_version != requested_version:
        raise AppError("DATA_VERSION_MISMATCH", "工具参数的数据版本与 Agent 运行版本不一致", status_code=409, details={"run_data_version": expected_version, "tool_data_version": requested_version})
    write = contract.category == "result_write"
    dataset_type = str(params.get("dataset_type") or ("agent" if write else params.get("source_type") or "public"))
    authorize_tool(user, permission_code=contract.permission_code, dataset_type=dataset_type, region_code=_region_code(params), write=write, confirmation_type=contract.confirmation_type if contract.requires_confirmation else None, session=session)
    if contract.idempotency_required:
        idempotency_key = ensure_idempotency_key(idempotency_key)
    call_id, duplicate = start_tool_call(session, user, run_id, contract, input_summary=_bounded(params), idempotency_key=idempotency_key)
    if duplicate:
        return _existing_call(session, call_id, run_id)
    started = time.perf_counter()
    try:
        if tool_name == "analysis.result.write":
            result = _write_analysis(session, run_id, params, run)
        elif tool_name == "score.result.write":
            result = _write_score(session, run_id, params, run)
        elif tool_name == "expansion.result.write":
            result = _write_expansion(session, run_id, params, run, idempotency_key or "")
        else:
            result = _dispatch(session, settings, user, run_id, tool_name, params)
        duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        # Idempotent writes must be replayable byte-for-byte; read tools keep a
        # bounded summary so a large retrieval cannot inflate `tool_call`.
        stored = {"_result": result if contract.idempotency_required else _bounded(result)}
        finish_tool_call(session, call_id, status="SUCCEEDED", output_summary=stored, duration_ms=duration_ms)
        _update_snapshot(session, run_id, tool_name=tool_name, result=result)
        record_audit_event(session, action="AGENT_TOOL_EXECUTED", resource_type="tool_call", resource_id=str(call_id), actor_user_id=user.user_id, after_state={"run_id": run_id, "tool_name": tool_name, "status": "SUCCEEDED", "duration_ms": duration_ms}, commit=True)
        return ToolExecuteResponse(run_id=run_id, tool_name=tool_name, tool_call_id=call_id, status="SUCCEEDED", result=_json_value(result), duration_ms=duration_ms)
    except Exception as exc:
        duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        # A failed SQL statement leaves the SQLAlchemy transaction unusable
        # until rollback; clear it before writing the failure trace.
        if isinstance(exc, SQLAlchemyError):
            session.rollback()
        if isinstance(exc, AppError):
            error_code, message, retryable = exc.error_code, exc.message, exc.retryable
            details = exc.details or {}
        elif isinstance(exc, EmbeddingServiceError):
            error_code, message, retryable = exc.code, exc.message, True
            details = {}
        elif isinstance(exc, (ValueError, TypeError)):
            error_code, message, retryable = "INVALID_INPUT", str(exc), False
            details = {}
        elif isinstance(exc, SQLAlchemyError):
            error_code, message, retryable = "DB_ERROR", "数据库暂时不可用，请稍后重试", True
            details = {}
        else:
            error_code, message, retryable = "TOOL_EXECUTION_ERROR", str(exc), error_code in contract.retryable_error_codes if "error_code" in locals() else False
            details = {}
        error = {"error_code": error_code, "message": message, "retryable": retryable, "details": details}
        finish_tool_call(session, call_id, status="FAILED", output_summary={"_error": error}, error_code=error_code, retryable=retryable, duration_ms=duration_ms)
        _update_snapshot(session, run_id, tool_name=tool_name, result={}, error=error)
        record_audit_event(session, action="AGENT_TOOL_FAILED", resource_type="tool_call", resource_id=str(call_id), actor_user_id=user.user_id, severity="WARNING", after_state={"run_id": run_id, "tool_name": tool_name, "status": "FAILED", "error_code": error_code, "retryable": retryable, "duration_ms": duration_ms}, commit=True)
        raise AppError("AGENT_TOOL_EXECUTION_FAILED", f"工具 {tool_name} 执行失败：{message}", status_code=502 if retryable else 400, retryable=retryable, details={"tool_name": tool_name, "tool_call_id": call_id, "error_code": error_code, "message": message, "details": details}) from exc
