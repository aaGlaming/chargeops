"""Read services for regions, operators, stations and connectors."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.catalog import ConnectorQuery, MapPoint, OperatorSummary, RegionSummary, SourceInfo, StationQuery


@dataclass(frozen=True)
class TableColumns:
    values: frozenset[str]

    def has(self, column: str) -> bool:
        return column in self.values


def table_columns(session: Session, table: str) -> TableColumns:
    rows = session.execute(text(f"SHOW COLUMNS FROM `{table}`")).all()
    return TableColumns(frozenset(str(row[0]) for row in rows))


def _col(alias: str, columns: TableColumns, preferred: str, fallback: str = "NULL") -> str:
    return f"{alias}.`{preferred}`" if columns.has(preferred) else fallback


def _active(alias: str, columns: TableColumns) -> str:
    return f"{alias}.deleted_at IS NULL" if columns.has("deleted_at") else "1=1"


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def parse_charging_types(value: Any) -> list[str]:
    value = _json_value(value)
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]
    return []


def source_info(row: Any) -> SourceInfo:
    return SourceInfo(
        source_type=str(row.get("source_type") or "unknown"),
        source_url=row.get("source_url"),
        source_file=row.get("source_file"),
        data_version=str(row.get("data_version") or "unknown"),
        import_batch_id=int(row["import_batch_id"]) if row.get("import_batch_id") is not None else None,
    )


def page_meta(page: int, page_size: int, total: int):
    from app.schemas.catalog import PageMeta

    return PageMeta(page=page, page_size=page_size, total=total, has_next=page * page_size < total)


def _region_summary(row: Any) -> RegionSummary:
    return RegionSummary(
        id=int(row["region_id"] if row.get("region_id") is not None else row["id"]),
        region_code=str(row["region_code"]),
        name=str(row["region_name"] if row.get("region_name") is not None else row["name"]),
        parent_region_id=int(row["parent_region_id"]) if row.get("parent_region_id") is not None else None,
        region_type=row.get("region_type"),
        country_code=row.get("country_code"),
        station_count=int(row.get("station_count") or 0),
        source=source_info(row),
    )


def _operator_summary(row: Any) -> OperatorSummary:
    return OperatorSummary(
        id=int(row["operator_id"] if row.get("operator_id") is not None else row["id"]),
        operator_code=row.get("operator_code"),
        operator_name=str(row["operator_name"]),
        station_count=int(row.get("station_count") or 0),
        source=source_info(row),
    )


def list_regions(session: Session, *, region_code: str | None, page: int, page_size: int) -> tuple[list[RegionSummary], int]:
    rc = table_columns(session, "region")
    sc = table_columns(session, "charging_station")
    conditions = [_active("r", rc)]
    params: dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}
    if region_code:
        conditions.append("r.region_code=:region_code")
        params["region_code"] = region_code
    where = " AND ".join(conditions)
    region_type = _col("r", rc, "region_type")
    country_code = _col("r", rc, "country_code")
    parent_id = _col("r", rc, "parent_region_id")
    source_file = _col("r", rc, "source_file")
    source_batch = _col("r", rc, "import_batch_id")
    count_sql = f"SELECT COUNT(*) FROM region r WHERE {where}"
    total = int(session.execute(text(count_sql), params).scalar_one())
    sql = f"""SELECT r.id, r.region_code, r.name, {parent_id} AS parent_region_id,
        {region_type} AS region_type, {country_code} AS country_code,
        r.source_type, r.source_url, {source_file} AS source_file, r.data_version,
        {source_batch} AS import_batch_id,
        (SELECT COUNT(*) FROM charging_station s WHERE s.region_id=r.id AND {_active('s', sc)}) AS station_count
        FROM region r WHERE {where} ORDER BY r.name LIMIT :limit OFFSET :offset"""
    rows = session.execute(text(sql), params).mappings().all()
    return [_region_summary(row) for row in rows], total


def get_region(session: Session, region_code: str) -> tuple[RegionSummary, list[RegionSummary]] | None:
    rc = table_columns(session, "region")
    sc = table_columns(session, "charging_station")
    fields = f"r.id, r.region_code, r.name, {_col('r', rc, 'parent_region_id')} AS parent_region_id, {_col('r', rc, 'region_type')} AS region_type, {_col('r', rc, 'country_code')} AS country_code, r.source_type, r.source_url, {_col('r', rc, 'source_file')} AS source_file, r.data_version, {_col('r', rc, 'import_batch_id')} AS import_batch_id, (SELECT COUNT(*) FROM charging_station s WHERE s.region_id=r.id AND {_active('s', sc)}) AS station_count"
    row = session.execute(text(f"SELECT {fields} FROM region r WHERE r.region_code=:code AND {_active('r', rc)} ORDER BY r.data_version DESC LIMIT 1"), {"code": region_code}).mappings().one_or_none()
    if row is None:
        return None
    summary = _region_summary(row)
    parent_clause = "r.parent_region_id=:parent_id" if rc.has("parent_region_id") else "1=0"
    children = session.execute(text(f"SELECT {fields} FROM region r WHERE {parent_clause} AND {_active('r', rc)} ORDER BY r.name"), {"parent_id": summary.id}).mappings().all()
    return summary, [_region_summary(child) for child in children]


def list_operators(session: Session, *, operator_name: str | None, page: int, page_size: int) -> tuple[list[OperatorSummary], int]:
    oc = table_columns(session, "operator")
    sc = table_columns(session, "charging_station")
    conditions = [_active("o", oc)]
    params: dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}
    if operator_name:
        conditions.append("o.operator_name LIKE :operator_name")
        params["operator_name"] = f"%{operator_name}%"
    where = " AND ".join(conditions)
    count = int(session.execute(text(f"SELECT COUNT(*) FROM `operator` o WHERE {where}"), params).scalar_one())
    sql = f"""SELECT o.id, {_col('o', oc, 'operator_code')} AS operator_code, o.operator_name,
        o.source_type, o.source_url, {_col('o', oc, 'source_file')} AS source_file, o.data_version,
        {_col('o', oc, 'import_batch_id')} AS import_batch_id,
        (SELECT COUNT(*) FROM charging_station s WHERE s.operator_id=o.id AND {_active('s', sc)}) AS station_count
        FROM `operator` o WHERE {where} ORDER BY o.operator_name LIMIT :limit OFFSET :offset"""
    rows = session.execute(text(sql), params).mappings().all()
    return [_operator_summary(row) for row in rows], count


def get_operator(session: Session, operator_id: int) -> tuple[OperatorSummary, list[dict[str, Any]]] | None:
    oc = table_columns(session, "operator")
    sc = table_columns(session, "charging_station")
    fields = f"o.id, {_col('o', oc, 'operator_code')} AS operator_code, o.operator_name, {_col('o', oc, 'website_url')} AS website_url, o.source_type, o.source_url, {_col('o', oc, 'source_file')} AS source_file, o.data_version, {_col('o', oc, 'import_batch_id')} AS import_batch_id, (SELECT COUNT(*) FROM charging_station s WHERE s.operator_id=o.id AND {_active('s', sc)}) AS station_count"
    row = session.execute(text(f"SELECT {fields} FROM `operator` o WHERE o.id=:operator_id AND {_active('o', oc)}"), {"operator_id": operator_id}).mappings().one_or_none()
    if row is None:
        return None
    operator = _operator_summary(row)
    stations, _ = list_stations(session, StationQuery(operator_id=operator_id, page=1, page_size=20))
    return operator, stations


def _station_select(sc: TableColumns, rc: TableColumns, oc: TableColumns) -> str:
    status = _col("s", sc, "station_status", _col("s", sc, "status_code", "'UNKNOWN'"))
    access = _col("s", sc, "access_type", _col("s", sc, "access_code", "'UNKNOWN'"))
    charging = _col("s", sc, "charging_types", _col("s", sc, "ev_connector_types"))
    country = _col("s", sc, "country_code", _col("s", sc, "country"))
    effective = _col("s", sc, "effective_date", _col("s", sc, "open_date"))
    return f"""s.id, s.external_station_id, {_col('s', sc, 'external_station_key')} AS external_station_key,
        s.station_name, {_col('s', sc, 'street_address')} AS street_address, s.city, s.state,
        {_col('s', sc, 'zip_code')} AS zip_code, {country} AS country_code, s.latitude, s.longitude,
        {status} AS station_status, {access} AS access_type, {_col('s', sc, 'facility_type')} AS facility_type,
        {charging} AS charging_types_raw, s.total_connector_count, {_col('s', sc, 'date_last_confirmed')} AS date_last_confirmed,
        {effective} AS effective_date, s.source_type, s.source_url, {_col('s', sc, 'source_file')} AS source_file,
        s.data_version, {_col('s', sc, 'import_batch_id')} AS import_batch_id,
        r.id AS region_id, r.region_code, r.name AS region_name, {_col('r', rc, 'parent_region_id')} AS parent_region_id,
        {_col('r', rc, 'region_type')} AS region_type, {_col('r', rc, 'country_code')} AS region_country_code,
        r.source_type AS region_source_type, r.source_url AS region_source_url, {_col('r', rc, 'source_file')} AS region_source_file,
        r.data_version AS region_data_version, {_col('r', rc, 'import_batch_id')} AS region_import_batch_id,
        o.id AS operator_id, {_col('o', oc, 'operator_code')} AS operator_code, o.operator_name,
        o.source_type AS operator_source_type, o.source_url AS operator_source_url, {_col('o', oc, 'source_file')} AS operator_source_file,
        o.data_version AS operator_data_version, {_col('o', oc, 'import_batch_id')} AS operator_import_batch_id"""


def _station_item(row: Any) -> dict[str, Any]:
    region = None
    if row.get("region_id") is not None:
        region_row = dict(row)
        region_row.update({"id": row["region_id"], "name": row["region_name"], "source_type": row["region_source_type"], "source_url": row["region_source_url"], "source_file": row["region_source_file"], "data_version": row["region_data_version"], "import_batch_id": row["region_import_batch_id"], "country_code": row["region_country_code"]})
        region = _region_summary(region_row)
    operator = None
    if row.get("operator_id") is not None:
        operator_row = dict(row)
        operator_row.update({"id": row["operator_id"], "operator_code": row["operator_code"], "source_type": row["operator_source_type"], "source_url": row["operator_source_url"], "source_file": row["operator_source_file"], "data_version": row["operator_data_version"], "import_batch_id": row["operator_import_batch_id"], "station_count": 0})
        operator = _operator_summary(operator_row)
    return {
        "id": int(row["id"]), "external_station_id": int(row["external_station_id"]), "external_station_key": row.get("external_station_key"),
        "station_name": row["station_name"], "street_address": row.get("street_address"), "city": row.get("city"), "state": row.get("state"),
        "zip_code": row.get("zip_code"), "country_code": row.get("country_code"), "latitude": float(row["latitude"]) if row.get("latitude") is not None else None,
        "longitude": float(row["longitude"]) if row.get("longitude") is not None else None, "station_status": str(row.get("station_status") or "UNKNOWN"),
        "access_type": str(row.get("access_type") or "UNKNOWN"), "facility_type": row.get("facility_type"), "charging_types": parse_charging_types(row.get("charging_types_raw")),
        "total_connector_count": int(row.get("total_connector_count") or 0), "date_last_confirmed": str(row["date_last_confirmed"]) if row.get("date_last_confirmed") else None,
        "effective_date": str(row["effective_date"]) if row.get("effective_date") else None, "region": region, "operator": operator, "source": source_info(row),
    }


def _station_conditions(query: StationQuery, sc: TableColumns, params: dict[str, Any]) -> list[str]:
    conditions = [_active("s", sc)]
    status = _col("s", sc, "station_status", _col("s", sc, "status_code", "NULL"))
    access = _col("s", sc, "access_type", _col("s", sc, "access_code", "NULL"))
    charging = _col("s", sc, "charging_types", _col("s", sc, "ev_connector_types", "NULL"))
    for value, expression, key in ((query.station_status, status, "station_status"), (query.access_type, access, "access_type")):
        if value:
            conditions.append(f"UPPER({expression})=UPPER(:{key})")
            params[key] = value
    if query.region_code:
        conditions.append("r.region_code=:region_code")
        params["region_code"] = query.region_code
    if query.operator_id:
        conditions.append("s.operator_id=:operator_id")
        params["operator_id"] = query.operator_id
    if query.charging_type:
        conditions.append(f"UPPER(COALESCE({charging},'')) LIKE CONCAT('%',UPPER(:charging_type),'%')")
        params["charging_type"] = query.charging_type
    if query.source_type:
        conditions.append("s.source_type=:source_type")
        params["source_type"] = query.source_type
    if query.data_version:
        conditions.append("s.data_version=:data_version")
        params["data_version"] = query.data_version
    if query.min_latitude is not None:
        conditions.append("s.latitude>=:min_latitude")
        params["min_latitude"] = query.min_latitude
    if query.max_latitude is not None:
        conditions.append("s.latitude<=:max_latitude")
        params["max_latitude"] = query.max_latitude
    if query.min_longitude is not None:
        conditions.append("s.longitude>=:min_longitude")
        params["min_longitude"] = query.min_longitude
    if query.max_longitude is not None:
        conditions.append("s.longitude<=:max_longitude")
        params["max_longitude"] = query.max_longitude
    if query.radius_km is not None:
        if query.latitude is None or query.longitude is None:
            raise ValueError("latitude and longitude are required when radius_km is provided")
        lat_delta = query.radius_km / 111.0
        lon_delta = query.radius_km / max(111.0 * math.cos(math.radians(query.latitude)), 0.1)
        conditions.extend([
            "s.latitude BETWEEN :radius_min_lat AND :radius_max_lat",
            "s.longitude BETWEEN :radius_min_lon AND :radius_max_lon",
            "6371 * ACOS(LEAST(1, GREATEST(-1, COS(RADIANS(:latitude)) * COS(RADIANS(s.latitude)) * COS(RADIANS(s.longitude) - RADIANS(:longitude)) + SIN(RADIANS(:latitude)) * SIN(RADIANS(s.latitude))))) <= :radius_km",
        ])
        params.update({"latitude": query.latitude, "longitude": query.longitude, "radius_km": query.radius_km, "radius_min_lat": query.latitude - lat_delta, "radius_max_lat": query.latitude + lat_delta, "radius_min_lon": query.longitude - lon_delta, "radius_max_lon": query.longitude + lon_delta})
    return conditions


def list_stations(session: Session, query: StationQuery) -> tuple[list[dict[str, Any]], int]:
    sc, rc, oc = table_columns(session, "charging_station"), table_columns(session, "region"), table_columns(session, "operator")
    params: dict[str, Any] = {"limit": query.page_size, "offset": (query.page - 1) * query.page_size}
    conditions = _station_conditions(query, sc, params)
    where = " AND ".join(conditions)
    total = int(session.execute(text(f"SELECT COUNT(*) FROM charging_station s LEFT JOIN region r ON r.id=s.region_id WHERE {where}"), params).scalar_one())
    rows = session.execute(text(f"SELECT {_station_select(sc, rc, oc)} FROM charging_station s LEFT JOIN region r ON r.id=s.region_id LEFT JOIN `operator` o ON o.id=s.operator_id WHERE {where} ORDER BY s.station_name, s.id LIMIT :limit OFFSET :offset"), params).mappings().all()
    return [_station_item(row) for row in rows], total


def get_station(session: Session, station_id: int) -> dict[str, Any] | None:
    sc, rc, oc = table_columns(session, "charging_station"), table_columns(session, "region"), table_columns(session, "operator")
    row = session.execute(text(f"SELECT {_station_select(sc, rc, oc)} FROM charging_station s LEFT JOIN region r ON r.id=s.region_id LEFT JOIN `operator` o ON o.id=s.operator_id WHERE s.id=:station_id AND {_active('s', sc)}"), {"station_id": station_id}).mappings().one_or_none()
    if row is None:
        return None
    item = _station_item(row)
    connectors, _ = list_connectors(session, ConnectorQuery(station_id=station_id, page=1, page_size=500))
    metric_count = int(session.execute(text("SELECT COUNT(*) FROM station_operation_metric WHERE station_id=:station_id"), {"station_id": station_id}).scalar_one())
    fault_count = int(session.execute(text("SELECT COUNT(*) FROM station_fault_event WHERE station_id=:station_id"), {"station_id": station_id}).scalar_one())
    expansion_count = int(session.execute(text("SELECT COUNT(*) FROM expansion_plan WHERE station_id=:station_id"), {"station_id": station_id}).scalar_one())
    item.update({"connectors": connectors, "related": {
        "operation_metrics": {"count": metric_count, "href": f"/stations/{station_id}/metrics"},
        "fault_events": {"count": fault_count, "href": f"/stations/{station_id}/faults"},
        "agent_runs": {"count": 0, "href": f"/agent-runs?station_id={station_id}"},
        "expansion_plans": {"count": expansion_count, "href": f"/stations/{station_id}/expansion-plans"},
    }})
    return item


def list_connectors(session: Session, query: ConnectorQuery) -> tuple[list[dict[str, Any]], int]:
    cc = table_columns(session, "charging_connector")
    conditions = [_active("c", cc)]
    params: dict[str, Any] = {"limit": query.page_size, "offset": (query.page - 1) * query.page_size}
    if query.station_id:
        conditions.append("c.station_id=:station_id")
        params["station_id"] = query.station_id
    if query.connector_type:
        conditions.append("UPPER(c.connector_type)=UPPER(:connector_type)")
        params["connector_type"] = query.connector_type
    if query.connector_status and cc.has("connector_status"):
        conditions.append("UPPER(c.connector_status)=UPPER(:connector_status)")
        params["connector_status"] = query.connector_status
    if query.source_type:
        conditions.append("c.source_type=:source_type")
        params["source_type"] = query.source_type
    if query.data_version:
        conditions.append("c.data_version=:data_version")
        params["data_version"] = query.data_version
    where = " AND ".join(conditions)
    total = int(session.execute(text(f"SELECT COUNT(*) FROM charging_connector c WHERE {where}"), params).scalar_one())
    power = _col("c", cc, "power_kw")
    status = _col("c", cc, "connector_status")
    sql = f"""SELECT c.id, c.station_id, c.connector_type, c.quantity, {power} AS power_kw, {status} AS connector_status,
        c.source_type, c.source_url, {_col('c', cc, 'source_file')} AS source_file, c.data_version,
        {_col('c', cc, 'import_batch_id')} AS import_batch_id
        FROM charging_connector c WHERE {where} ORDER BY c.station_id, c.connector_type LIMIT :limit OFFSET :offset"""
    rows = session.execute(text(sql), params).mappings().all()
    items = [{"id": int(row["id"]), "station_id": int(row["station_id"]), "connector_type": row["connector_type"], "quantity": int(row["quantity"] or 0), "power_kw": float(row["power_kw"]) if row.get("power_kw") is not None else None, "connector_status": row.get("connector_status"), "source": source_info(row)} for row in rows]
    return items, total


def map_points(session: Session, query: StationQuery, limit: int = 5000) -> tuple[list[MapPoint], int]:
    query = query.model_copy(update={"page": 1, "page_size": limit})
    items, total = list_stations(session, query)
    points = [MapPoint(id=item["id"], station_name=item["station_name"], latitude=item["latitude"], longitude=item["longitude"], station_status=item["station_status"], access_type=item["access_type"], total_connector_count=item["total_connector_count"], source_type=item["source"].source_type, data_version=item["source"].data_version, region_code=item["region"].region_code if item["region"] else None, operator_name=item["operator"].operator_name if item["operator"] else None) for item in items if item["latitude"] is not None and item["longitude"] is not None]
    return points, total
