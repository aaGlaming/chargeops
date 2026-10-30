"""Deterministic coverage-gap analysis and the Coverage Gap Agent contract.

The Supervisor owns orchestration.  This module owns the business rules that
must remain reproducible when the language model is unavailable: boundary
validation, spatial coverage, fast-charging coverage, nearest-station distance,
temporal gaps and freshness checks.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from typing import Any

from app.agents.contracts import CoverageGapInput


COVERAGE_GAP_SYSTEM_PROMPT = """
你是 ChargeOps 覆盖缺口分析 Agent。你只能基于 Supervisor 提供的区域边界、
充电站、连接器、运营指标和已校验 RAG 证据生成解释。覆盖结论必须区分：

1. 空间缺口：区域面积、站点密度、覆盖半径和区域代表点到最近站点距离；
2. 快充缺口：快充连接器数量、快充站点比例和快充阈值；
3. 时段缺口：按小时运营指标识别高峰占用或缺少时段数据；
4. 数据不足：区域无有效边界、站点无有效坐标、站点数据过期、连接器或
   时段指标缺失、RAG 没有可回溯证据。

确定性计算结果优先于模型猜测。不得补造区域边界、站点、政策条款或运营
指标。每个解释都要引用已校验的原文片段和数据版本；数据不足时明确停止，
不要输出建设批准或投资承诺。
""".strip()


FAST_CONNECTOR_TYPES = {
    "DC_FAST",
    "DCFC",
    "FAST",
    "LEVEL_3",
    "CCS",
    "CHADEMO",
    "直流快充",
    "快充",
}


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


def _point(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    longitude, latitude = _float(value[0]), _float(value[1])
    if longitude is None or latitude is None or not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        return None
    return longitude, latitude


def _rings(geometry: dict[str, Any]) -> list[list[tuple[float, float]]]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Polygon" and isinstance(coordinates, list):
        return [[point for point in (_point(item) for item in ring) if point] for ring in coordinates if isinstance(ring, list)]
    if geometry_type == "MultiPolygon" and isinstance(coordinates, list):
        rings: list[list[tuple[float, float]]] = []
        for polygon in coordinates:
            if isinstance(polygon, list):
                rings.extend([[point for point in (_point(item) for item in ring) if point] for ring in polygon if isinstance(ring, list)])
        return rings
    return []


def parse_boundary(region: dict[str, Any]) -> tuple[list[list[tuple[float, float]]], tuple[float, float] | None]:
    """Return polygon rings and a representative point from a GeoJSON region."""

    boundary = _json(region.get("boundary_geojson") or region.get("boundary"))
    if isinstance(boundary, dict) and boundary.get("type") == "Feature":
        boundary = boundary.get("geometry")
    if not isinstance(boundary, dict):
        return [], None
    rings = [ring for ring in _rings(boundary) if len(ring) >= 3]
    if not rings:
        return [], None
    outer = rings[0]
    representative_points = outer[:-1] if len(outer) > 3 and outer[0] == outer[-1] else outer
    longitude = sum(point[0] for point in representative_points) / len(representative_points)
    latitude = sum(point[1] for point in representative_points) / len(representative_points)
    return rings, (longitude, latitude)


def _inside(point: tuple[float, float], ring: list[tuple[float, float]]) -> bool:
    x, y = point
    inside = False
    previous = ring[-1]
    for current in ring:
        x1, y1 = previous
        x2, y2 = current
        intersects = (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1
        if intersects:
            inside = not inside
        previous = current
    return inside


def point_in_boundary(point: tuple[float, float], rings: list[list[tuple[float, float]]]) -> bool:
    if not rings or not _inside(point, rings[0]):
        return False
    return not any(_inside(point, hole) for hole in rings[1:])


def _haversine_km(first: tuple[float, float], second: tuple[float, float]) -> float:
    longitude1, latitude1 = map(math.radians, first)
    longitude2, latitude2 = map(math.radians, second)
    dlat, dlon = latitude2 - latitude1, longitude2 - longitude1
    a = math.sin(dlat / 2) ** 2 + math.cos(latitude1) * math.cos(latitude2) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1.0, a)))


def _polygon_area_km2(ring: list[tuple[float, float]]) -> float:
    if len(ring) < 3:
        return 0.0
    mean_lat = math.radians(sum(point[1] for point in ring) / len(ring))
    scale_x = 111.320 * math.cos(mean_lat)
    scale_y = 110.574
    area = 0.0
    for first, second in zip(ring, ring[1:] + ring[:1]):
        area += (first[0] * scale_x) * (second[1] * scale_y) - (second[0] * scale_x) * (first[1] * scale_y)
    return abs(area) / 2


def _connector_type(item: dict[str, Any]) -> str:
    return str(item.get("connector_type") or "").strip().upper().replace("-", "_").replace(" ", "_")


def _station_types(item: dict[str, Any]) -> set[str]:
    values = _json(item.get("charging_types")) or _json(item.get("charging_types_raw")) or []
    if isinstance(values, str):
        values = values.replace(";", ",").split(",")
    return {str(value).strip().upper().replace("-", "_").replace(" ", "_") for value in values if str(value).strip()}


def _freshness(stations: list[dict[str, Any]], as_of: date, stale_after_days: int) -> dict[str, Any]:
    dates = [_date(item.get("date_last_confirmed") or item.get("effective_date")) for item in stations]
    dates = [value for value in dates if value]
    newest = max(dates) if dates else None
    age = (as_of - newest).days if newest else None
    return {
        "latest_data_date": newest.isoformat() if newest else None,
        "age_days": age,
        "stale_after_days": stale_after_days,
        "status": "UNKNOWN" if newest is None else "STALE" if age is not None and age > stale_after_days else "CURRENT",
    }


def _temporal_metrics(metrics: list[dict[str, Any]], occupancy_threshold: float) -> dict[str, Any]:
    if not metrics:
        return {"status": "UNKNOWN", "observed_hours": [], "gap_hours": [], "peak_occupancy_rate": None}
    by_hour: dict[int, list[float]] = {}
    for item in metrics:
        hour = item.get("metric_hour")
        occupancy = _float(item.get("occupancy_rate"))
        if hour is None or occupancy is None:
            continue
        by_hour.setdefault(int(hour), []).append(occupancy)
    averages = {hour: round(sum(values) / len(values), 4) for hour, values in by_hour.items()}
    gap_hours = sorted(hour for hour, value in averages.items() if value >= occupancy_threshold)
    return {
        "status": "GAP" if gap_hours else "NO_GAP",
        "observed_hours": sorted(averages),
        "gap_hours": gap_hours,
        "peak_occupancy_rate": max(averages.values()) if averages else None,
        "occupancy_threshold": occupancy_threshold,
    }


def analyze_coverage_gap(
    payload: CoverageGapInput | dict[str, Any],
    *,
    region: dict[str, Any] | None,
    stations: list[dict[str, Any]],
    connectors: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
    as_of: date | None = None,
) -> dict[str, Any]:
    """Calculate a reproducible coverage result with explicit insufficiency reasons."""

    input_data = payload if isinstance(payload, CoverageGapInput) else CoverageGapInput.model_validate(payload)
    analysis_date = as_of or input_data.analysis_date or date.today()
    insufficiency: list[str] = []
    gap_types: list[str] = []
    if not region:
        insufficiency.append("REGION_NOT_FOUND")
        return _stopped("MISSING_BUSINESS_DATA", "未找到目标区域", gap_types, insufficiency, input_data.data_version)
    rings, representative = parse_boundary(region)
    if not rings or representative is None:
        insufficiency.append("REGION_BOUNDARY_MISSING")
        return _stopped("MISSING_BUSINESS_DATA", "区域缺少有效 GeoJSON 边界，无法计算空间覆盖", gap_types, insufficiency, input_data.data_version)
    if not stations:
        insufficiency.append("STATIONS_EMPTY")
        return _stopped("MISSING_BUSINESS_DATA", "区域没有可分析的充电站", gap_types, insufficiency, input_data.data_version)
    valid_stations = []
    invalid_coordinates = 0
    outside_boundary = 0
    for station in stations:
        point = (_float(station.get("longitude")), _float(station.get("latitude")))
        if point[0] is None or point[1] is None or not (-180 <= point[0] <= 180 and -90 <= point[1] <= 90):
            invalid_coordinates += 1
            continue
        if not point_in_boundary((point[0], point[1]), rings):
            outside_boundary += 1
            continue
        valid_stations.append((station, (point[0], point[1])))
    if not valid_stations:
        insufficiency.append("VALID_COORDINATES_EMPTY")
        return _stopped("MISSING_BUSINESS_DATA", "区域内没有有效站点坐标", gap_types, insufficiency, input_data.data_version)
    if invalid_coordinates:
        insufficiency.append("INVALID_COORDINATES")
    if outside_boundary:
        insufficiency.append("STATIONS_OUTSIDE_BOUNDARY")
    freshness = _freshness([item for item, _ in valid_stations], analysis_date, input_data.stale_after_days)
    if freshness["status"] == "STALE":
        return _stopped("STALE_DATA", "区域站点数据已超过允许的新鲜度窗口", gap_types, insufficiency + ["STATION_DATA_STALE"], input_data.data_version, freshness=freshness)

    area = _polygon_area_km2(rings[0])
    if area <= 0:
        insufficiency.append("REGION_AREA_INVALID")
        return _stopped("MISSING_BUSINESS_DATA", "区域边界面积无效", gap_types, insufficiency, input_data.data_version)
    station_count = len(valid_stations)
    expected = max(1.0, area / (math.pi * input_data.coverage_radius_km ** 2))
    coverage_score = round(min(1.0, station_count / expected), 4)
    nearest = round(min(_haversine_km(representative, point) for _, point in valid_stations), 4)
    station_density = round(station_count / area, 4)

    station_ids = {int(item.get("id")) for item, _ in valid_stations if item.get("id") is not None}
    connector_rows = [item for item in connectors if item.get("station_id") in station_ids]
    if not connector_rows:
        insufficiency.append("CONNECTORS_EMPTY")
    total_connectors = sum(int(item.get("quantity") or 0) for item in connector_rows)
    fast_connectors = sum(int(item.get("quantity") or 0) for item in connector_rows if _connector_type(item) in FAST_CONNECTOR_TYPES)
    if not connector_rows:
        for station, _ in valid_stations:
            types = _station_types(station)
            if types:
                total_connectors += int(station.get("total_connector_count") or 0)
                fast_connectors += int(station.get("total_connector_count") or 0) if types & FAST_CONNECTOR_TYPES else 0
    if total_connectors == 0:
        insufficiency.append("CONNECTOR_QUANTITY_MISSING")
    fast_ratio = round(fast_connectors / total_connectors, 4) if total_connectors else 0.0
    temporal = _temporal_metrics(metrics, input_data.time_gap_occupancy_threshold)
    if temporal["status"] == "UNKNOWN":
        insufficiency.append("TIME_METRICS_MISSING")

    if coverage_score < input_data.threshold or nearest > input_data.coverage_radius_km:
        gap_types.append("SPATIAL_COVERAGE")
    if input_data.charger_type in {"ALL", "FAST"} and fast_ratio < input_data.fast_ratio_threshold:
        gap_types.append("FAST_CHARGING")
    if temporal["status"] == "GAP":
        gap_types.append("TIME_WINDOW")
    if insufficiency:
        gap_types.append("DATA_INSUFFICIENT")

    return {
        "status": "COMPLETED",
        "coverage_score": coverage_score,
        "gap_types": gap_types,
        "data_insufficiency": sorted(set(insufficiency)),
        "metrics": {
            "region_area_km2": round(area, 4),
            "station_count": station_count,
            "connector_count": total_connectors,
            "fast_connector_count": fast_connectors,
            "fast_ratio": fast_ratio,
            "station_density_per_sq_km": station_density,
            "nearest_station_distance_km": nearest,
            "expected_station_count": round(expected, 4),
            "coverage_radius_km": input_data.coverage_radius_km,
            "threshold": input_data.threshold,
            "fast_ratio_threshold": input_data.fast_ratio_threshold,
            "temporal": temporal,
            "invalid_coordinate_count": invalid_coordinates,
            "outside_boundary_count": outside_boundary,
        },
        "station_count": station_count,
        "connector_count": total_connectors,
        "fast_station_count": sum(1 for station, _ in valid_stations if _station_types(station) & FAST_CONNECTOR_TYPES),
        "fast_ratio": fast_ratio,
        "nearest_station_distance_km": nearest,
        "station_density_per_sq_km": station_density,
        "temporal_gap": temporal,
        "freshness": freshness,
        "region_code": region.get("region_code"),
        "data_version": input_data.data_version or region.get("data_version"),
    }


def _stopped(
    reason: str,
    conclusion: str,
    gap_types: list[str],
    insufficiency: list[str],
    data_version: str | None,
    *,
    freshness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": reason,
        "stop_reason": reason,
        "conclusion": conclusion,
        "coverage_score": None,
        "gap_types": gap_types + ["DATA_INSUFFICIENT"],
        "data_insufficiency": sorted(set(insufficiency)),
        "metrics": {},
        "freshness": freshness or {},
        "data_version": data_version,
    }


__all__ = ["COVERAGE_GAP_SYSTEM_PROMPT", "FAST_CONNECTOR_TYPES", "analyze_coverage_gap", "parse_boundary", "point_in_boundary"]
