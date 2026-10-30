"""Deterministic candidate-site scoring and Site Selection Agent prompt."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

from app.agents.contracts import SiteSelectionInput


SITE_SELECTION_SYSTEM_PROMPT = """
你是 ChargeOps 候选选址 Agent。你只能基于候选站点、区域、周边站点、交通/人口
指标、建设条件和已校验的 RAG 证据解释选址结果。确定性代码负责总分、等级、
排序和扣分原因，Prompt 不得改写权重或计算结果。

输出必须包含覆盖缺口、交通、人口、竞争、建设条件、政策适配和数据可信度分项，
并说明缺失字段、数据版本、评分规则版本、政策证据和推荐动作。缺失关键字段或
数据过期时降低可信度，最高只能给出保守等级，不得自动生成高等级推荐；不得把
评分结果当成建设审批或投资承诺。
""".strip()


DEFAULT_SCORING_RULE_VERSION = "site-selection-score-v1"
DEFAULT_WEIGHTS: dict[str, float] = {
    "coverage": 0.25,
    "traffic": 0.20,
    "population": 0.15,
    "competition": 0.15,
    "construction": 0.15,
    "policy": 0.10,
}
CRITICAL_FIELDS = (
    "region",
    "latitude",
    "longitude",
    "area_sqm",
    "parking_spaces",
    "electric_capacity_kw",
    "budget_usd",
    "traffic_index",
    "population_density",
    "planned_open_date",
)


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


def _haversine_km(first: tuple[float, float], second: tuple[float, float]) -> float:
    longitude1, latitude1 = map(math.radians, first)
    longitude2, latitude2 = map(math.radians, second)
    dlat, dlon = latitude2 - latitude1, longitude2 - longitude1
    a = math.sin(dlat / 2) ** 2 + math.cos(latitude1) * math.cos(latitude2) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1.0, a)))


def _normalize_weights(raw: dict[str, Any]) -> dict[str, float]:
    weights = dict(DEFAULT_WEIGHTS)
    for key, value in (raw or {}).items():
        if key in weights:
            numeric = _float(value)
            if numeric is not None and numeric >= 0:
                weights[key] = numeric
    total = sum(weights.values()) or 1.0
    return {key: round(value / total, 6) for key, value in weights.items()}


def _normalized(value: Any, maximum: float | None) -> float | None:
    numeric = _float(value)
    if numeric is None:
        return None
    if maximum is None or maximum <= 0:
        return 0.0
    return round(min(100.0, max(0.0, numeric / maximum * 100.0)), 3)


def _construction_score(candidate: dict[str, Any]) -> tuple[float, list[str]]:
    missing: list[str] = []
    components: list[float] = []
    capacity = _float(candidate.get("electric_capacity_kw"))
    area = _float(candidate.get("area_sqm"))
    parking = _float(candidate.get("parking_spaces"))
    budget = _float(candidate.get("budget_usd"))
    for field, value, cap in (
        ("electric_capacity_kw", capacity, 500.0),
        ("area_sqm", area, 1000.0),
        ("parking_spaces", parking, 50.0),
        ("budget_usd", budget, 500000.0),
    ):
        if value is None:
            missing.append(field)
            components.append(0.0)
        else:
            components.append(min(100.0, max(0.0, value / cap * 100.0)))
    return round(sum(components) / len(components), 3), missing


def _stopped(reason: str, message: str, data_version: str | None) -> dict[str, Any]:
    return {
        "status": reason,
        "stop_reason": reason,
        "conclusion": message,
        "ranked_candidates": [],
        "selected_candidate_id": None,
        "scoring_breakdown": {},
        "scoring_rule_version": DEFAULT_SCORING_RULE_VERSION,
        "weights": DEFAULT_WEIGHTS,
        "missing_data": ["CANDIDATES_EMPTY"],
        "recommendation_actions": ["补充候选站点后重试"],
        "data_version": data_version,
    }


def analyze_site_selection(
    payload: SiteSelectionInput | dict[str, Any],
    *,
    candidates: list[dict[str, Any]],
    regions: list[dict[str, Any]],
    stations: list[dict[str, Any]],
    as_of: date | None = None,
) -> dict[str, Any]:
    """Score and rank candidates using versioned deterministic rules."""

    input_data = payload if isinstance(payload, SiteSelectionInput) else SiteSelectionInput.model_validate(payload)
    if not candidates:
        return _stopped("MISSING_BUSINESS_DATA", "没有可评估的候选站点", input_data.data_version)
    analysis_date = as_of or date.today()
    weights = _normalize_weights(input_data.weights)
    rule_version = input_data.scoring_rule_version or DEFAULT_SCORING_RULE_VERSION
    max_traffic = max((_float(item.get("traffic_index")) or 0.0 for item in candidates), default=0.0)
    max_population = max((_float(item.get("population_density")) or 0.0 for item in candidates), default=0.0)
    region_codes = {str(item.get("region_code")) for item in regions if item.get("region_code")}
    ranked: list[dict[str, Any]] = []
    all_missing: set[str] = set()
    valid_station_count = 0

    for candidate in candidates:
        candidate_id = candidate.get("id", candidate.get("candidate_site_id"))
        missing: list[str] = []
        deductions: list[str] = []
        region = candidate.get("region") if isinstance(candidate.get("region"), dict) else None
        region_code = region.get("region_code") if region else None
        if not region_code:
            missing.append("region")
        elif region_codes and region_code not in region_codes:
            missing.append("region_reference")
        for field in CRITICAL_FIELDS:
            if field == "region":
                continue
            if candidate.get(field) is None and field not in missing:
                missing.append(field)
        latitude, longitude = _float(candidate.get("latitude")), _float(candidate.get("longitude"))
        if latitude is None or longitude is None:
            missing.extend(["latitude", "longitude"])
            nearby: list[tuple[dict[str, Any], float]] = []
        else:
            nearby = []
            for station in stations:
                station_lat, station_lon = _float(station.get("latitude")), _float(station.get("longitude"))
                if station_lat is None or station_lon is None:
                    continue
                distance = _haversine_km((longitude, latitude), (station_lon, station_lat))
                if distance <= input_data.nearby_radius_km:
                    nearby.append((station, distance))
            valid_station_count += len(nearby)
        if not stations:
            missing.append("nearby_stations")
        nearest_distance = min((distance for _, distance in nearby), default=None)
        coverage_score = 100.0 if nearest_distance is None and stations else round(min(100.0, nearest_distance / input_data.nearby_radius_km * 100.0), 3) if nearest_distance is not None else 0.0
        competition_score = round(max(0.0, 100.0 - min(100.0, len(nearby) / 20.0 * 100.0)), 3) if stations else 0.0
        traffic_score = _normalized(candidate.get("traffic_index"), max_traffic)
        population_score = _normalized(candidate.get("population_density"), max_population)
        construction_score, construction_missing = _construction_score(candidate)
        missing.extend(construction_missing)
        if traffic_score is None:
            missing.append("traffic_index")
            traffic_score = 0.0
        if population_score is None:
            missing.append("population_density")
            population_score = 0.0
        policy_score = _float(candidate.get("policy_score"))
        if policy_score is None:
            policy_score = 50.0
            missing.append("policy_match_pending")
        policy_score = round(min(100.0, max(0.0, policy_score)), 3)

        completeness = candidate.get("completeness") if isinstance(candidate.get("completeness"), dict) else {}
        completeness_score = _float(completeness.get("score"))
        if completeness_score is None:
            completeness_score = max(0.0, 1.0 - len(set(missing)) / len(CRITICAL_FIELDS))
        freshness = candidate.get("freshness") if isinstance(candidate.get("freshness"), dict) else {}
        freshness_status = freshness.get("status")
        data_as_of = _date(candidate.get("data_as_of"))
        if freshness_status is None and data_as_of:
            freshness_status = "CURRENT" if (analysis_date - data_as_of).days <= input_data.stale_after_days else "STALE"
        if freshness_status == "STALE":
            missing.append("candidate_data_stale")
            deductions.append("候选站点数据已过期")
        if freshness_status in {None, "UNKNOWN"}:
            missing.append("candidate_freshness")
        confidence = completeness_score * 100.0
        if freshness_status == "STALE":
            confidence *= 0.4
        elif freshness_status in {None, "UNKNOWN"}:
            confidence *= 0.75
        if not stations:
            confidence *= 0.7
        if "policy_match_pending" in missing:
            confidence *= 0.8
        if "nearby_stations" in missing:
            confidence *= 0.7
        if missing:
            deductions.extend([f"缺少 {field}" for field in sorted(set(missing))])
        confidence = round(min(100.0, max(0.0, confidence)), 3)
        breakdown = {
            "coverage": round(coverage_score, 3),
            "traffic": round(traffic_score, 3),
            "population": round(population_score, 3),
            "competition": round(competition_score, 3),
            "construction": round(construction_score, 3),
            "policy": round(policy_score, 3),
        }
        total_score = round(sum(breakdown[key] * weights[key] for key in weights), 3)
        critical_missing = set(missing) & set(CRITICAL_FIELDS)
        if confidence < input_data.min_data_confidence * 100 or critical_missing:
            grade = "C"
            recommendation = "补齐关键字段并完成人工复核后再推荐"
        elif total_score >= 80:
            grade = "A"
            recommendation = "进入人工复核和建设条件核验"
        elif total_score >= 65:
            grade = "B"
            recommendation = "作为备选点，补充政策和工程核验"
        else:
            grade = "C"
            recommendation = "暂不推荐，先补充数据或调整方案"
        all_missing.update(missing)
        ranked.append({
            "candidate_site_id": candidate_id,
            "site_name": candidate.get("site_name"),
            "region_code": region_code,
            "total_score": total_score,
            "scoring_breakdown": breakdown,
            "coverage_score": breakdown["coverage"],
            "traffic_score": breakdown["traffic"],
            "population_score": breakdown["population"],
            "competition_score": breakdown["competition"],
            "construction_score": breakdown["construction"],
            "policy_score": breakdown["policy"],
            "data_confidence_score": confidence,
            "recommendation_grade": grade,
            "missing_data": sorted(set(missing)),
            "deduction_reasons": sorted(set(deductions)),
            "nearby_station_count": len(nearby),
            "nearest_station_distance_km": round(nearest_distance, 4) if nearest_distance is not None else None,
            "recommendation_action": recommendation,
        })

    ranked.sort(key=lambda item: (-item["total_score"], -item["data_confidence_score"], str(item.get("candidate_site_id"))))
    selected = ranked[0] if ranked else None
    return {
        "status": "COMPLETED",
        "ranked_candidates": ranked,
        "selected_candidate_id": selected.get("candidate_site_id") if selected else None,
        "scoring_breakdown": {
            "rule_version": rule_version,
            "weights": weights,
            "candidate_count": len(candidates),
            "nearby_radius_km": input_data.nearby_radius_km,
            "valid_nearby_station_rows": valid_station_count,
        },
        "scoring_rule_version": rule_version,
        "weights": weights,
        "missing_data": sorted(all_missing),
        "recommendation_actions": [selected["recommendation_action"]] if selected else ["补充候选站点后重试"],
        "data_version": input_data.data_version or (selected and next((item.get("source", {}).get("data_version") for item in candidates if item.get("source")), None)),
    }


__all__ = ["DEFAULT_SCORING_RULE_VERSION", "DEFAULT_WEIGHTS", "SITE_SELECTION_SYSTEM_PROMPT", "analyze_site_selection"]
