"""Deterministic competition analysis and the Competition Agent prompt."""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from typing import Any

from app.agents.contracts import CompetitionInput


COMPETITION_SYSTEM_PROMPT = """
你是 ChargeOps 竞争格局分析 Agent。你只能基于指定坐标、半径内的站点、
运营商、连接器和功率数据，以及已校验的 RAG 原文解释竞争格局。必须输出：

1. 周边竞争站点及其距离权重；
2. 运营商分布、距离加权份额和集中度 HHI；
3. 充电类型、连接器数量和功率分组；
4. 服务空白、竞争风险和数据不足分类。

确定性计算结果优先于模型猜测。不得补造运营商、功率、服务评价或政策条款。
当站点、坐标、连接器或数据新鲜度不足时明确标记或停止。所有规则解释必须
引用已通过 Chunk 和原文位置校验的 RAG 证据，不得把竞争分析直接当成建设批准。
""".strip()


FAST_TYPES = {"FAST", "DC_FAST", "DCFC", "LEVEL_3", "CCS", "CHADEMO", "快充", "直流快充"}


def _json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


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


def _types(value: Any) -> set[str]:
    parsed = _json(value) or []
    if isinstance(parsed, str):
        parsed = parsed.replace(";", ",").split(",")
    return {str(item).strip().upper().replace("-", "_").replace(" ", "_") for item in parsed if str(item).strip()}


def _haversine_km(first: tuple[float, float], second: tuple[float, float]) -> float:
    longitude1, latitude1 = map(math.radians, first)
    longitude2, latitude2 = map(math.radians, second)
    dlat, dlon = latitude2 - latitude1, longitude2 - longitude1
    a = math.sin(dlat / 2) ** 2 + math.cos(latitude1) * math.cos(latitude2) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1.0, a)))


def _operator(item: dict[str, Any]) -> tuple[str, str | None]:
    nested = item.get("operator") if isinstance(item.get("operator"), dict) else {}
    name = str(item.get("operator_name") or nested.get("operator_name") or "UNKNOWN")
    code = item.get("operator_code") or nested.get("operator_code")
    return name, str(code) if code else None


def _power_group(power: float | None) -> str:
    if power is None:
        return "UNKNOWN"
    if power < 50:
        return "LT_50_KW"
    if power < 150:
        return "50_149_KW"
    if power < 350:
        return "150_349_KW"
    return "GTE_350_KW"


def _stopped(reason: str, message: str, insufficiency: list[str], data_version: str | None) -> dict[str, Any]:
    return {
        "status": reason,
        "stop_reason": reason,
        "conclusion": message,
        "competition_index": None,
        "nearby_stations": [],
        "operator_distribution": {},
        "operator_concentration": {},
        "charging_type_distribution": {},
        "connector_power_groups": {},
        "service_gaps": ["DATA_INSUFFICIENT"],
        "risk_flags": ["DATA_INSUFFICIENT"],
        "metrics": {},
        "data_insufficiency": sorted(set(insufficiency)),
        "freshness": {},
        "data_version": data_version,
    }


def analyze_competition(
    payload: CompetitionInput | dict[str, Any],
    *,
    stations: list[dict[str, Any]],
    connectors: list[dict[str, Any]],
    as_of: date | None = None,
) -> dict[str, Any]:
    """Calculate distance-weighted competition metrics without model guesses."""

    input_data = payload if isinstance(payload, CompetitionInput) else CompetitionInput.model_validate(payload)
    analysis_date = as_of or input_data.analysis_date or date.today()
    center = (input_data.longitude, input_data.latitude)
    insufficiency: list[str] = []
    if not stations:
        return _stopped("MISSING_BUSINESS_DATA", "指定半径内没有竞争站点", ["NEARBY_STATIONS_EMPTY"], input_data.data_version)

    rows: list[tuple[dict[str, Any], float, float]] = []
    invalid_coordinates = 0
    for item in stations:
        latitude, longitude = _float(item.get("latitude")), _float(item.get("longitude"))
        if latitude is None or longitude is None or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            invalid_coordinates += 1
            continue
        distance = _haversine_km(center, (longitude, latitude))
        if distance <= input_data.radius_km:
            weight = math.exp(-distance / input_data.distance_decay_km)
            rows.append((item, distance, weight))
    if invalid_coordinates:
        insufficiency.append("INVALID_COORDINATES")
    if not rows:
        return _stopped("MISSING_BUSINESS_DATA", "半径内没有带有效坐标的竞争站点", insufficiency + ["VALID_COORDINATES_EMPTY"], input_data.data_version)

    dates = [_date(item.get("date_last_confirmed") or item.get("effective_date")) for item, _, _ in rows]
    valid_dates = [value for value in dates if value]
    newest = max(valid_dates) if valid_dates else None
    age_days = (analysis_date - newest).days if newest else None
    freshness = {
        "latest_data_date": newest.isoformat() if newest else None,
        "age_days": age_days,
        "stale_after_days": input_data.stale_after_days,
        "status": "UNKNOWN" if newest is None else "STALE" if age_days is not None and age_days > input_data.stale_after_days else "CURRENT",
    }
    if freshness["status"] == "STALE":
        return _stopped("STALE_DATA", "竞争站点数据已超过允许的新鲜度窗口", insufficiency + ["STATION_DATA_STALE"], input_data.data_version)
    if newest is None:
        insufficiency.append("STATION_FRESHNESS_UNKNOWN")

    if input_data.operator_code:
        rows = [row for row in rows if _operator(row[0])[1] == input_data.operator_code]
        if not rows:
            return _stopped("MISSING_BUSINESS_DATA", "指定运营商在目标半径内没有站点", insufficiency + ["OPERATOR_FILTER_EMPTY"], input_data.data_version)

    station_ids = {int(item["id"]) for item, _, _ in rows if item.get("id") is not None}
    connector_rows = [item for item in connectors if item.get("station_id") in station_ids]
    if not connector_rows:
        insufficiency.append("CONNECTORS_EMPTY")

    operator_distribution: dict[str, int] = {}
    weighted_operator: dict[str, float] = {}
    charging_distribution: dict[str, int] = {}
    power_groups: dict[str, int] = {}
    total_connectors = 0
    known_power_kw = 0.0
    known_power_rows = 0
    for item, _, weight in rows:
        name, _ = _operator(item)
        operator_distribution[name] = operator_distribution.get(name, 0) + 1
        weighted_operator[name] = weighted_operator.get(name, 0.0) + weight
        types = _types(item.get("charging_types") or item.get("charging_types_raw"))
        for charging_type in types or {"UNKNOWN"}:
            charging_distribution[charging_type] = charging_distribution.get(charging_type, 0) + 1
    for connector in connector_rows:
        quantity = int(connector.get("quantity") or 0)
        connector_type = str(connector.get("connector_type") or "UNKNOWN").upper().replace("-", "_")
        charging_distribution[connector_type] = charging_distribution.get(connector_type, 0) + quantity
        total_connectors += quantity
        power = _float(connector.get("power_kw"))
        power_groups[_power_group(power)] = power_groups.get(_power_group(power), 0) + quantity
        if power is not None:
            known_power_kw += power * quantity
            known_power_rows += quantity
    if total_connectors == 0:
        fallback_connectors = sum(int(item.get("total_connector_count") or 0) for item, _, _ in rows)
        total_connectors = fallback_connectors
        if fallback_connectors == 0:
            insufficiency.append("CONNECTOR_QUANTITY_MISSING")
    if not power_groups:
        power_groups["UNKNOWN"] = total_connectors
        insufficiency.append("POWER_DATA_MISSING")

    operator_total = sum(operator_distribution.values()) or 1
    shares = {key: round(value / operator_total, 4) for key, value in operator_distribution.items()}
    hhi = round(sum(share * share for share in shares.values()), 4)
    weighted_total = sum(weighted_operator.values()) or 1.0
    weighted_shares = {key: round(value / weighted_total, 4) for key, value in weighted_operator.items()}
    weighted_presence = round(sum(weighted_operator.values()), 4)
    density = len(rows) / (math.pi * input_data.radius_km ** 2)
    density_score = min(100.0, density / 10.0 * 100.0)
    concentration_score = hhi * 100.0
    weighted_score = min(100.0, weighted_presence / max(1.0, len(rows)) * 100.0)
    competition_index = round(min(100.0, density_score * 0.4 + concentration_score * 0.35 + weighted_score * 0.25), 4)
    top_operator, top_share = max(shares.items(), key=lambda item: item[1])
    nearest_distance = min(distance for _, distance, _ in rows)
    fast_quantity = sum(
        int(item.get("quantity") or 0)
        for item in connector_rows
        if str(item.get("connector_type") or "").upper().replace("-", "_") in FAST_TYPES
    )

    service_gaps: list[str] = []
    if nearest_distance > input_data.radius_km * 0.5:
        service_gaps.append("DISTANCE_SERVICE_GAP")
    if fast_quantity == 0:
        service_gaps.append("NO_FAST_CHARGING")
    if total_connectors < input_data.service_gap_connector_threshold:
        service_gaps.append("LOW_CONNECTOR_SUPPLY")
    if known_power_rows == 0:
        service_gaps.append("POWER_DATA_UNAVAILABLE")
    elif known_power_kw < input_data.service_gap_power_kw_threshold:
        service_gaps.append("LOW_POWER_SUPPLY")
    if len(operator_distribution) <= 1:
        service_gaps.append("OPERATOR_SERVICE_CONCENTRATION")
    if insufficiency:
        service_gaps.append("DATA_INSUFFICIENT")

    risk_flags: list[str] = []
    if competition_index >= 70:
        risk_flags.append("HIGH_COMPETITION")
    if hhi >= 0.5 or top_share >= 0.8:
        risk_flags.append("HIGH_OPERATOR_CONCENTRATION")
    if service_gaps:
        risk_flags.append("SERVICE_DIFFERENTIATION_REQUIRED")
    if insufficiency:
        risk_flags.append("DATA_INSUFFICIENT")

    nearby = []
    for item, distance, weight in sorted(rows, key=lambda row: (row[1], int(row[0].get("id") or 0)))[:200]:
        name, code = _operator(item)
        nearby.append({
            "station_id": item.get("id"),
            "station_name": item.get("station_name"),
            "distance_km": round(distance, 4),
            "distance_weight": round(weight, 4),
            "operator_name": name,
            "operator_code": code,
            "charging_types": sorted(_types(item.get("charging_types") or item.get("charging_types_raw"))),
            "connector_count": int(item.get("total_connector_count") or 0),
            "source": item.get("source"),
        })

    return {
        "status": "COMPLETED",
        "radius_km": input_data.radius_km,
        "nearby_station_count": len(rows),
        "nearby_stations": nearby,
        "operator_distribution": operator_distribution,
        "operator_concentration": {
            "hhi": hhi,
            "top_operator": top_operator,
            "top_operator_share": top_share,
            "weighted_shares": weighted_shares,
        },
        "charging_type_distribution": charging_distribution,
        "connector_power_groups": {
            "quantity_by_power_group": power_groups,
            "total_connectors": total_connectors,
            "known_power_kw": round(known_power_kw, 3),
            "known_power_connector_count": known_power_rows,
        },
        "service_gaps": service_gaps,
        "risk_flags": risk_flags,
        "metrics": {
            "hhi": hhi,
            "station_density_per_sq_km": round(density, 4),
            "distance_weighted_presence": weighted_presence,
            "distance_weighted_operator_shares": weighted_shares,
            "nearest_station_distance_km": round(nearest_distance, 4),
            "fast_connector_count": fast_quantity,
            "operator_count": len(operator_distribution),
            "invalid_coordinate_count": invalid_coordinates,
        },
        "data_insufficiency": sorted(set(insufficiency)),
        "freshness": freshness,
        "data_version": input_data.data_version,
    }


__all__ = ["COMPETITION_SYSTEM_PROMPT", "analyze_competition"]
