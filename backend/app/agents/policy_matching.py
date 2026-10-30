"""Deterministic policy and subsidy matching rules for the Policy Agent."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from app.agents.contracts import PolicyMatchingInput


POLICY_MATCHING_SYSTEM_PROMPT = """
你是 ChargeOps 政策与补贴匹配 Agent。你只能基于 MySQL 中的候选站点字段、政策
条件矩阵、申请主体、建设规模、计划日期和已校验的 RAG 原文生成匹配草案。
确定性代码负责逐项条件比较、有效期判断、材料缺口、匹配状态和可信度；模型不得
修改条件结果、金额、政策版本或截止日期。

每条政策必须标记通过、部分通过、不通过或无法判断，并列出实际值、要求值、缺失
字段、缺少材料、生效日期、申请截止日期和政策版本。缺少候选站点字段或原文证据
时不得假装符合资格；匹配结果只用于人工审核和申请准备，不代表政策审批或补贴承诺。
""".strip()


DEFAULT_RULE_VERSION = "policy-matching-v1"
PASS = "PASS"
PARTIAL = "PARTIAL"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN"


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None
    return None


def _json_value(value: Any) -> Any:
    if isinstance(value, (dict, list, int, float, bool)) or value is None:
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return value


def _materials(value: Any) -> list[str]:
    parsed = _json_value(value)
    if isinstance(parsed, list):
        return sorted({str(item).strip() for item in parsed if str(item).strip()})
    if parsed is None:
        return []
    return sorted({part.strip() for part in str(parsed).replace("；", ";").split(";") if part.strip()})


def _normal(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().lower()
    return value


def _subject(candidate: dict[str, Any] | None, payload: PolicyMatchingInput) -> dict[str, Any]:
    subject = payload.model_dump(mode="json")
    attributes = subject.pop("attributes", {})
    if isinstance(attributes, dict):
        subject.update(attributes)
    if candidate:
        region = candidate.get("region") if isinstance(candidate.get("region"), dict) else {}
        subject.update({
            "candidate_site_id": candidate.get("id"),
            "candidate_site_external_id": candidate.get("external_candidate_id"),
            "site_name": candidate.get("site_name"),
            "region_code": region.get("region_code") or subject.get("region_code"),
            "site_type": candidate.get("site_type") or candidate.get("facility_type") or subject.get("site_type"),
            "electric_capacity_kw": candidate.get("electric_capacity_kw"),
            "budget_usd": candidate.get("budget_usd"),
            "traffic_index": candidate.get("traffic_index"),
            "population_density": candidate.get("population_density"),
            "data_as_of": candidate.get("data_as_of"),
        })
    subject["applicant_type"] = subject.get("subject_type")
    subject["planned_budget_usd"] = subject.get("project_budget_usd")
    return subject


def _pairs(policy: dict[str, Any]) -> list[tuple[str, Any]]:
    key = str(policy.get("condition_key") or "").strip()
    expected = _json_value(policy.get("condition_value"))
    pairs: list[tuple[str, Any]] = []
    if key.startswith("eligibility:"):
        pairs.append(("candidate_site_external_id", key.split(":", 1)[1]))
    if isinstance(expected, dict):
        pairs.extend((str(item_key), item_value) for item_key, item_value in expected.items())
    elif key:
        pairs.append((key, expected))
    return pairs


def _actual(subject: dict[str, Any], key: str) -> Any:
    aliases = {
        "applicant": "subject_type",
        "applicant_type": "subject_type",
        "planned_budget": "project_budget_usd",
        "planned_budget_usd": "project_budget_usd",
        "scale_kw": "planned_scale_kw",
        "site_external_id": "candidate_site_external_id",
    }
    direct = aliases.get(key, key)
    value = subject.get(direct)
    if value is None and ":" in key:
        value = subject.get(key.split(":", 1)[0])
    return value


def _compare(actual: Any, expected: Any, operator: str) -> tuple[str, str]:
    if actual is None:
        return UNKNOWN, "缺少实际字段"
    operator = operator.upper().replace("EQUALS", "EQ")
    try:
        if operator in {"EQ", "="}:
            ok = _normal(actual) == _normal(expected)
        elif operator in {"GTE", ">="}:
            ok = float(actual) >= float(expected)
        elif operator in {"LTE", "<="}:
            ok = float(actual) <= float(expected)
        elif operator == "GT":
            ok = float(actual) > float(expected)
        elif operator == "LT":
            ok = float(actual) < float(expected)
        elif operator in {"IN", "NOT_IN"}:
            values = expected if isinstance(expected, list) else [part.strip() for part in str(expected).split(",")]
            ok = _normal(actual) in {_normal(item) for item in values}
            if operator == "NOT_IN":
                ok = not ok
        elif operator == "CONTAINS":
            values = actual if isinstance(actual, list) else str(actual).split(",")
            ok = _normal(expected) in {_normal(item) for item in values}
        else:
            return UNKNOWN, f"不支持的操作符 {operator}"
    except (TypeError, ValueError):
        return UNKNOWN, "实际值或要求值无法比较"
    return (PASS, "条件通过") if ok else (FAIL, "条件不通过")


def _policy_result(policy: dict[str, Any], subject: dict[str, Any], planned_date: date | None, available_materials: set[str]) -> dict[str, Any]:
    condition_results: list[dict[str, Any]] = []
    operator = str(policy.get("condition_operator") or "EQ")
    for key, expected in _pairs(policy):
        actual = _actual(subject, key)
        status, reason = _compare(actual, expected, operator)
        condition_results.append({"condition_key": key, "operator": operator, "expected": expected, "actual": actual, "status": status, "reason": reason})
    effective_from = _date(policy.get("effective_from"))
    effective_to = _date(policy.get("effective_to"))
    deadline = _date(policy.get("application_deadline"))
    missing_fields = sorted({item["condition_key"] for item in condition_results if item["status"] == UNKNOWN})
    statuses = [item["status"] for item in condition_results]
    if planned_date and effective_from and planned_date < effective_from:
        statuses.append(UNKNOWN)
        missing_fields.append("effective_from")
    if planned_date and effective_to and planned_date > effective_to:
        statuses.append(FAIL)
        condition_results.append({"condition_key": "effective_to", "operator": "GTE", "expected": effective_to.isoformat(), "actual": planned_date.isoformat(), "status": FAIL, "reason": "政策已失效"})
    if planned_date and deadline and planned_date > deadline:
        statuses.append(FAIL)
        condition_results.append({"condition_key": "application_deadline", "operator": "GTE", "expected": deadline.isoformat(), "actual": planned_date.isoformat(), "status": FAIL, "reason": "申请截止日期已过"})
    required_materials = _materials(policy.get("required_materials"))
    missing_materials = sorted(set(required_materials) - available_materials)
    if any(status == FAIL for status in statuses):
        match_status = FAIL
    elif any(status == UNKNOWN for status in statuses):
        match_status = PARTIAL if any(status == PASS for status in statuses) else UNKNOWN
    elif missing_materials:
        match_status = PARTIAL
    elif statuses and all(status == PASS for status in statuses):
        match_status = PASS
    else:
        match_status = UNKNOWN
    return {
        "policy_id": policy.get("id"),
        "policy_code": policy.get("policy_code"),
        "policy_version": policy.get("policy_version"),
        "title": policy.get("title"),
        "policy_type": policy.get("policy_type"),
        "applicant_type": policy.get("applicant_type"),
        "match_status": match_status,
        "condition_results": condition_results,
        "missing_fields": sorted(set(missing_fields)),
        "required_materials": required_materials,
        "missing_materials": missing_materials,
        "effective_from": effective_from.isoformat() if effective_from else None,
        "effective_to": effective_to.isoformat() if effective_to else None,
        "application_deadline": deadline.isoformat() if deadline else None,
        "source_url": policy.get("source_url"),
        "source_file": policy.get("source_file"),
        "data_version": policy.get("data_version"),
    }


def _stopped(reason: str, message: str, data_version: str | None) -> dict[str, Any]:
    return {
        "status": reason,
        "stop_reason": reason,
        "conclusion": message,
        "policy_matches": [],
        "matched_policies": [],
        "partial_policies": [],
        "failed_policies": [],
        "unknown_policies": [],
        "required_materials": [],
        "missing_materials": [],
        "missing_fields": ["POLICIES_EMPTY"],
        "missing_conditions": ["POLICIES_EMPTY"],
        "policy_versions": [],
        "deadlines": [],
        "match_summary": {"total": 0, "pass": 0, "partial": 0, "fail": 0, "unknown": 0},
        "data_confidence_score": 0.0,
        "scoring_rule_version": DEFAULT_RULE_VERSION,
        "data_version": data_version,
    }


def analyze_policy_matching(
    payload: PolicyMatchingInput | dict[str, Any],
    *,
    policies: list[dict[str, Any]],
    candidates: list[dict[str, Any]] | None = None,
    subject: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Match every applicable policy and expose each condition decision."""

    input_data = payload if isinstance(payload, PolicyMatchingInput) else PolicyMatchingInput.model_validate(payload)
    if not policies:
        return _stopped("MISSING_BUSINESS_DATA", "没有可匹配的政策条件", input_data.data_version)
    candidates = candidates or []
    candidate_subjects = [_subject(candidate, input_data) for candidate in candidates]
    if not candidate_subjects:
        base_subject = _subject(None, input_data)
        if isinstance(subject, dict):
            base_subject.update(subject)
        candidate_subjects = [base_subject]
    planned_date = input_data.planned_date or date.today()
    available_materials = {item.strip() for item in input_data.available_materials if item.strip()}
    results: list[dict[str, Any]] = []
    for subject in candidate_subjects:
        for policy in policies:
            match = _policy_result(policy, subject, planned_date, available_materials)
            match.update({
                "candidate_site_id": subject.get("candidate_site_id"),
                "candidate_site_external_id": subject.get("candidate_site_external_id"),
                "site_name": subject.get("site_name"),
            })
            results.append(match)
    pass_results = [item for item in results if item["match_status"] == PASS]
    partial_results = [item for item in results if item["match_status"] == PARTIAL]
    fail_results = [item for item in results if item["match_status"] == FAIL]
    unknown_results = [item for item in results if item["match_status"] == UNKNOWN]
    required_materials = sorted({material for item in results for material in item["required_materials"]})
    missing_materials = sorted({material for item in results for material in item["missing_materials"]})
    missing_fields = sorted({field for item in results for field in item["missing_fields"]})
    versions = sorted({str(item.get("policy_version")) for item in results if item.get("policy_version")})
    deadlines = sorted({item["application_deadline"] for item in results if item.get("application_deadline")})
    confidence = 100.0
    if missing_fields:
        confidence *= max(0.2, 1.0 - min(0.8, len(missing_fields) / max(1, len(results))))
    if missing_materials:
        confidence *= 0.8
    return {
        "status": "COMPLETED",
        "conclusion": f"已匹配 {len(results)} 条政策结果，通过 {len(pass_results)} 条，部分通过 {len(partial_results)} 条，不通过 {len(fail_results)} 条，无法判断 {len(unknown_results)} 条。",
        "policy_matches": results,
        "matched_policies": pass_results,
        "partial_policies": partial_results,
        "failed_policies": fail_results,
        "unknown_policies": unknown_results,
        "required_materials": required_materials,
        "missing_materials": missing_materials,
        "missing_fields": missing_fields,
        "missing_conditions": missing_fields,
        "policy_versions": versions,
        "deadlines": deadlines,
        "match_summary": {"total": len(results), "pass": len(pass_results), "partial": len(partial_results), "fail": len(fail_results), "unknown": len(unknown_results)},
        "data_confidence_score": round(confidence, 3),
        "scoring_rule_version": input_data.policy_rule_version or DEFAULT_RULE_VERSION,
        "data_version": input_data.data_version,
    }


__all__ = ["DEFAULT_RULE_VERSION", "POLICY_MATCHING_SYSTEM_PROMPT", "analyze_policy_matching"]
