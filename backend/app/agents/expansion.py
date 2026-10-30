"""Deterministic station expansion planning and the Expansion Agent prompt."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

from app.agents.contracts import ExpansionInput


EXPANSION_SYSTEM_PROMPT = """
你是 ChargeOps 站点扩容 Agent。你只能基于站点运营指标、连接器占用/类型、故障
记录、电力容量和已校验的 RAG 原文生成扩容草案。确定性代码负责高峰占用、故障
集中度、新增快充/慢充数量、功率调整、预算区间和优先级；模型不得改写计算结果。

必须明确列出扩容前提、缺失数据、风险和数据可信度。缺少运营指标、故障记录或
电力容量时标记为待补充，不得假装数据完整。扩容方案永远进入人工确认，批准前
不得发布、审批或控制真实充电设备。原文解释只能来自已通过 Chunk 和原文位置
校验的扩容、设备安全、并网和运维规则。
""".strip()


DEFAULT_RULE_VERSION = "expansion-plan-v1"
FAST_TYPES = {"FAST", "DC_FAST", "DCFC", "LEVEL_3", "CCS", "CHADEMO", "快充", "直流快充"}


def _float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


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


def _connector_counts(connectors: list[dict[str, Any]], station_id: int, station: dict[str, Any]) -> tuple[int, int, float | None, list[str]]:
    rows = [item for item in connectors if int(item.get("station_id", -1)) == station_id]
    missing: list[str] = []
    fast = slow = 0
    known_power: float | None = 0.0
    if not rows:
        missing.append("CONNECTOR_DATA")
        total = int(station.get("total_connector_count") or 0)
        fast = int(total * 0.5) if total else 0
        slow = max(0, total - fast)
        known_power = None
        return fast, slow, known_power, missing
    for row in rows:
        quantity = int(row.get("quantity") or 0)
        connector_type = str(row.get("connector_type") or "").upper().replace("-", "_")
        if connector_type in FAST_TYPES:
            fast += quantity
        else:
            slow += quantity
        power = _float(row.get("power_kw"))
        if power is None:
            known_power = None
        elif known_power is not None:
            known_power += power * quantity
    if known_power is None:
        missing.append("POWER_CAPACITY")
    return fast, slow, known_power, missing


def _stopped(reason: str, message: str, data_version: str | None) -> dict[str, Any]:
    return {
        "status": reason,
        "stop_reason": reason,
        "conclusion": message,
        "confirmation_status": "NOT_REQUIRED",
        "plans": [],
        "risk_summary": ["DATA_INSUFFICIENT"],
        "scoring_rule_version": DEFAULT_RULE_VERSION,
        "metrics": {},
        "data_confidence_score": 0.0,
        "missing_data": ["STATIONS_EMPTY"],
        "data_version": data_version,
    }


def analyze_expansion(
    payload: ExpansionInput | dict[str, Any],
    *,
    stations: list[dict[str, Any]],
    connectors: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
    faults: list[dict[str, Any]],
    as_of: date | None = None,
) -> dict[str, Any]:
    """Generate bounded expansion plans and keep missing data explicit."""

    input_data = payload if isinstance(payload, ExpansionInput) else ExpansionInput.model_validate(payload)
    if not stations:
        return _stopped("MISSING_BUSINESS_DATA", "没有可扩容的站点业务数据", input_data.data_version)
    analysis_date = as_of or input_data.analysis_date or date.today()
    plans: list[dict[str, Any]] = []
    overall_risks: set[str] = set()
    overall_missing: set[str] = set()
    confidence_values: list[float] = []
    total_estimated_budget = 0.0

    for station in stations:
        station_id = int(station.get("id", station.get("station_id", 0)) or 0)
        station_metrics = [item for item in metrics if int(item.get("station_id", -1)) == station_id]
        station_faults = [item for item in faults if int(item.get("station_id", -1)) == station_id]
        missing: list[str] = []
        risks: list[str] = []
        occupancy_values = [_float(item.get("occupancy_rate")) for item in station_metrics]
        occupancy_values = [value for value in occupancy_values if value is not None]
        peak_occupancy = max(occupancy_values) if occupancy_values else None
        average_occupancy = sum(occupancy_values) / len(occupancy_values) if occupancy_values else None
        if peak_occupancy is None:
            missing.append("OPERATION_METRICS")
            risks.append("缺少运营指标，扩容数量只能作为待补充草案")
        metric_dates = [_date(item.get("data_as_of") or item.get("metric_date")) for item in station_metrics]
        metric_dates = [value for value in metric_dates if value]
        latest_metric_date = max(metric_dates) if metric_dates else None
        if latest_metric_date and (analysis_date - latest_metric_date).days > input_data.stale_after_days:
            missing.append("STALE_OPERATION_METRICS")
            risks.append("运营指标已过期")
        if not station_faults:
            missing.append("FAULT_HISTORY")
            risks.append("缺少故障记录，故障集中度无法完整评估")
        fault_count = len(station_faults)
        high_fault_count = sum(1 for item in station_faults if str(item.get("severity", "")).upper() in {"HIGH", "CRITICAL"})
        if high_fault_count:
            risks.append("高严重等级故障集中")
        fast_connectors, slow_connectors, known_power, connector_missing = _connector_counts(connectors, station_id, station)
        missing.extend(connector_missing)
        if "POWER_CAPACITY" in connector_missing:
            risks.append("缺少电力容量或连接器功率")
        if station.get("available_capacity_kw") is None and station.get("total_power_kw") is None and known_power is None:
            if "POWER_CAPACITY" not in missing:
                missing.append("POWER_CAPACITY")
        existing_connectors = fast_connectors + slow_connectors
        target = input_data.occupancy_target
        if peak_occupancy is None:
            proposed_fast = proposed_slow = 0
        else:
            overload = max(0.0, peak_occupancy - target)
            proposed_fast = math.ceil(overload * max(existing_connectors, 4))
            proposed_fast += math.ceil(high_fault_count / 2)
            if peak_occupancy >= input_data.high_occupancy_threshold and proposed_fast == 0:
                proposed_fast = 1
            proposed_slow = 1 if peak_occupancy >= target and proposed_fast == 0 else 0
        required_power = proposed_fast * input_data.fast_connector_power_kw + proposed_slow * 11.0
        available_capacity = _float(station.get("available_capacity_kw"))
        if available_capacity is None:
            available_capacity = known_power
        power_adjustment = None if available_capacity is None else round(max(0.0, required_power - available_capacity), 3)
        if power_adjustment and power_adjustment > 0:
            risks.append("现有容量不足，需要并网或功率调整")
        estimated_budget = round(proposed_fast * input_data.fast_connector_cost_usd + proposed_slow * input_data.slow_connector_cost_usd, 2)
        total_estimated_budget += estimated_budget
        priority = "HIGH" if (peak_occupancy is not None and peak_occupancy >= input_data.high_occupancy_threshold) or high_fault_count >= 2 else "MEDIUM" if (peak_occupancy is not None and peak_occupancy >= target) or fault_count >= 2 else "LOW"
        if input_data.budget_usd is not None and estimated_budget > input_data.budget_usd:
            risks.append("估算预算超过本次预算上限")
        confidence = 100.0
        if "OPERATION_METRICS" in missing or "STALE_OPERATION_METRICS" in missing:
            confidence *= 0.45
        if "FAULT_HISTORY" in missing:
            confidence *= 0.75
        if "POWER_CAPACITY" in missing:
            confidence *= 0.65
        if "CONNECTOR_DATA" in missing:
            confidence *= 0.75
        confidence = round(confidence, 3)
        confidence_values.append(confidence)
        overall_missing.update(missing)
        overall_risks.update(risks)
        plan_status = "WAITING_DATA" if missing else "READY_FOR_CONFIRMATION"
        plans.append({
            "station_id": station_id,
            "station_name": station.get("station_name"),
            "existing_fast_connectors": fast_connectors,
            "existing_slow_connectors": slow_connectors,
            "peak_occupancy_rate": round(peak_occupancy, 5) if peak_occupancy is not None else None,
            "average_occupancy_rate": round(average_occupancy, 5) if average_occupancy is not None else None,
            "fault_count_30d": fault_count,
            "high_severity_fault_count": high_fault_count,
            "available_capacity_kw": available_capacity,
            "proposed_fast_connectors": proposed_fast,
            "proposed_slow_connectors": proposed_slow,
            "power_adjustment_kw": power_adjustment,
            "requested_budget_usd": estimated_budget,
            "estimated_budget_usd": estimated_budget,
            "priority": priority,
            "status": plan_status,
            "data_confidence_score": confidence,
            "preconditions": sorted(set(["capacity_review", "safety_review"] + (["supplement_operation_metrics"] if "OPERATION_METRICS" in missing else []) + (["supplement_fault_history"] if "FAULT_HISTORY" in missing else []) + (["confirm_power_capacity"] if "POWER_CAPACITY" in missing else []))),
            "risk_summary": sorted(set(risks)),
            "missing_data": sorted(set(missing)),
        })

    if input_data.budget_usd is not None and total_estimated_budget > input_data.budget_usd:
        overall_risks.add("TOTAL_BUDGET_EXCEEDED")
    average_confidence = round(sum(confidence_values) / len(confidence_values), 3) if confidence_values else 0.0
    return {
        "status": "WAITING_CONFIRMATION",
        "confirmation_status": "PENDING",
        "plans": plans,
        "risk_summary": sorted(overall_risks) or ["方案发布前需要人工确认"],
        "scoring_rule_version": DEFAULT_RULE_VERSION,
        "metrics": {
            "station_count": len(stations),
            "total_estimated_budget_usd": round(total_estimated_budget, 2),
            "high_priority_station_count": sum(1 for plan in plans if plan["priority"] == "HIGH"),
            "total_proposed_fast_connectors": sum(plan["proposed_fast_connectors"] for plan in plans),
            "total_proposed_slow_connectors": sum(plan["proposed_slow_connectors"] for plan in plans),
        },
        "data_confidence_score": average_confidence,
        "missing_data": sorted(overall_missing),
        "data_version": input_data.data_version,
    }


__all__ = ["DEFAULT_RULE_VERSION", "EXPANSION_SYSTEM_PROMPT", "analyze_expansion"]
