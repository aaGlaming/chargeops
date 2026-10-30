"""Operations metrics, fault and candidate-site services."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.catalog import StationQuery
from app.schemas.operations import CandidateWrite, FaultCreate, FaultQuery, FaultUpdate, MetricQuery
from app.services.auth import UserContext, enforce_data_scope, record_audit_event
from app.services.catalog import _col, list_stations, page_meta, source_info, table_columns


CRITICAL_CANDIDATE_FIELDS = (
    "region_id", "latitude", "longitude", "area_sqm", "parking_spaces", "electric_capacity_kw",
    "budget_usd", "traffic_index", "population_density", "planned_open_date",
)


def _as_float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _as_date(value: Any) -> date | None:
    return value if isinstance(value, date) else None


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _page(page: int, page_size: int, total: int) -> dict[str, int | bool]:
    return page_meta(page, page_size, total).model_dump()


def list_metrics(session: Session, query: MetricQuery) -> tuple[list[dict[str, Any]], int]:
    conditions = ["m.deleted_at IS NULL"]
    params: dict[str, Any] = {"limit": query.page_size, "offset": (query.page - 1) * query.page_size}
    if query.station_id:
        conditions.append("m.station_id=:station_id")
        params["station_id"] = query.station_id
    if query.station_ids:
        placeholders = []
        for index, station_id in enumerate(query.station_ids):
            key = f"station_id_{index}"
            placeholders.append(f":{key}")
            params[key] = station_id
        conditions.append(f"m.station_id IN ({', '.join(placeholders)})")
    if query.start_date:
        conditions.append("m.metric_date>=:start_date")
        params["start_date"] = query.start_date
    if query.end_date:
        conditions.append("m.metric_date<=:end_date")
        params["end_date"] = query.end_date
    if query.metric_hour is not None:
        conditions.append("m.metric_hour=:metric_hour")
        params["metric_hour"] = query.metric_hour
    if query.source_type:
        conditions.append("m.source_type=:source_type")
        params["source_type"] = query.source_type
    if query.data_version:
        conditions.append("m.data_version=:data_version")
        params["data_version"] = query.data_version
    where = " AND ".join(conditions)
    total = int(session.execute(text(f"SELECT COUNT(*) FROM station_operation_metric m WHERE {where}"), params).scalar_one())
    rows = session.execute(text(f"""SELECT m.id, m.station_id, m.metric_date, m.metric_hour, m.timezone,
        m.charging_sessions, m.energy_kwh, m.peak_power_kw, m.occupancy_rate,
        m.avg_session_minutes, m.data_as_of, m.source_type, m.source_url, m.source_file,
        m.data_version, m.import_batch_id
        FROM station_operation_metric m WHERE {where}
        ORDER BY m.metric_date DESC, m.metric_hour DESC, m.id DESC LIMIT :limit OFFSET :offset"""), params).mappings().all()
    items = [{
        "id": int(row["id"]), "station_id": int(row["station_id"]), "metric_date": row["metric_date"], "metric_hour": row["metric_hour"],
        "timezone": row["timezone"], "charging_sessions": row["charging_sessions"], "energy_kwh": _as_float(row["energy_kwh"]),
        "peak_power_kw": _as_float(row["peak_power_kw"]), "occupancy_rate": _as_float(row["occupancy_rate"]),
        "avg_session_minutes": _as_float(row["avg_session_minutes"]), "data_as_of": row["data_as_of"], "source": source_info(row),
    } for row in rows]
    return items, total


def list_faults(session: Session, query: FaultQuery) -> tuple[list[dict[str, Any]], int]:
    conditions = ["f.deleted_at IS NULL"]
    params: dict[str, Any] = {"limit": query.page_size, "offset": (query.page - 1) * query.page_size}
    filters = ((query.station_id, "f.station_id=:station_id", "station_id"), (query.status, "f.status=:status", "status"), (query.severity, "f.severity=:severity", "severity"), (query.source_type, "f.source_type=:source_type", "source_type"), (query.data_version, "f.data_version=:data_version", "data_version"))
    for value, expression, key in filters:
        if value is not None:
            conditions.append(expression)
            params[key] = value
    if query.started_from:
        conditions.append("f.started_at>=:started_from")
        params["started_from"] = query.started_from
    if query.started_to:
        conditions.append("f.started_at<=:started_to")
        params["started_to"] = query.started_to
    where = " AND ".join(conditions)
    total = int(session.execute(text(f"SELECT COUNT(*) FROM station_fault_event f WHERE {where}"), params).scalar_one())
    rows = session.execute(text(f"""SELECT f.id, f.station_id, f.external_fault_id, f.fault_type, f.severity,
        f.started_at, f.recovered_at, f.affected_connectors, f.root_cause, f.status, f.data_as_of,
        f.source_type, f.source_url, f.source_file, f.data_version, f.import_batch_id
        FROM station_fault_event f WHERE {where}
        ORDER BY f.started_at DESC, f.id DESC LIMIT :limit OFFSET :offset"""), params).mappings().all()
    items = [{
        "id": int(row["id"]), "station_id": int(row["station_id"]), "external_fault_id": row["external_fault_id"],
        "fault_type": row["fault_type"], "severity": row["severity"], "started_at": row["started_at"], "recovered_at": row["recovered_at"],
        "affected_connectors": row["affected_connectors"], "root_cause": row["root_cause"], "status": row["status"],
        "data_as_of": row["data_as_of"], "source": source_info(row),
    } for row in rows]
    return items, total


def create_fault(session: Session, station_id: int, payload: FaultCreate, user: UserContext) -> dict[str, Any]:
    if payload.recovered_at and payload.recovered_at < payload.started_at:
        raise ValueError("recovered_at must be greater than or equal to started_at")
    station_exists = session.execute(text("SELECT COUNT(*) FROM charging_station WHERE id=:station_id"), {"station_id": station_id}).scalar_one()
    if not station_exists:
        raise LookupError("station not found")
    enforce_data_scope(user, dataset_type=payload.source_type, write=True)
    now = _now()
    status = "RECOVERED" if payload.recovered_at else "OPEN"
    data_version = payload.data_version or date.today().isoformat()
    session.execute(text("""INSERT INTO station_fault_event
        (station_id, external_fault_id, fault_type, severity, started_at, recovered_at, affected_connectors,
         root_cause, status, data_as_of, source_type, source_url, source_file, data_version, created_at, updated_at)
        VALUES (:station_id, :external_fault_id, :fault_type, :severity, :started_at, :recovered_at, :affected_connectors,
         :root_cause, :status, :data_as_of, :source_type, :source_url, :source_file, :data_version, :created_at, :updated_at)"""), {
        "station_id": station_id, "external_fault_id": payload.external_fault_id, "fault_type": payload.fault_type,
        "severity": payload.severity, "started_at": payload.started_at.replace(tzinfo=None), "recovered_at": payload.recovered_at.replace(tzinfo=None) if payload.recovered_at else None,
        "affected_connectors": payload.affected_connectors, "root_cause": payload.root_cause, "status": status,
        "data_as_of": payload.data_as_of, "source_type": payload.source_type, "source_url": payload.source_url,
        "source_file": payload.source_file, "data_version": data_version, "created_at": now, "updated_at": now,
    })
    fault_id = int(session.execute(text("SELECT LAST_INSERT_ID()")).scalar_one())
    record_audit_event(session, action="FAULT_CREATED", resource_type="station_fault_event", resource_id=str(fault_id), actor_user_id=user.user_id, after_state={"station_id": station_id, "severity": payload.severity}, commit=True)
    items, _ = list_faults(session, FaultQuery(station_id=station_id, page=1, page_size=500))
    return next(item for item in items if item["id"] == fault_id)


def update_fault(session: Session, fault_id: int, payload: FaultUpdate, user: UserContext) -> dict[str, Any]:
    current = session.execute(text("SELECT * FROM station_fault_event WHERE id=:id AND deleted_at IS NULL"), {"id": fault_id}).mappings().one_or_none()
    if current is None:
        raise LookupError("fault not found")
    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise ValueError("at least one fault field is required")
    if "recovered_at" in values and values["recovered_at"] and values["recovered_at"].replace(tzinfo=None) < current["started_at"]:
        raise ValueError("recovered_at must be greater than or equal to started_at")
    if values.get("recovered_at") and "status" not in values:
        values["status"] = "RECOVERED"
    if values.get("status") == "OPEN":
        values["recovered_at"] = None
    values["updated_at"] = _now()
    assignments = ", ".join(f"{key}=:{key}" for key in values)
    params = {key: (value.replace(tzinfo=None) if isinstance(value, datetime) else value) for key, value in values.items()}
    params["id"] = fault_id
    session.execute(text(f"UPDATE station_fault_event SET {assignments} WHERE id=:id"), params)
    record_audit_event(session, action="FAULT_UPDATED", resource_type="station_fault_event", resource_id=str(fault_id), actor_user_id=user.user_id, after_state=values, commit=True)
    items, _ = list_faults(session, FaultQuery(station_id=int(current["station_id"]), page=1, page_size=500))
    return next(item for item in items if item["id"] == fault_id)


def _candidate_quality(row: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    missing = [field for field in CRITICAL_CANDIDATE_FIELDS if row.get(field) is None]
    score = round((len(CRITICAL_CANDIDATE_FIELDS) - len(missing)) / len(CRITICAL_CANDIDATE_FIELDS), 4)
    evaluable = not missing
    data_as_of = _as_date(row.get("data_as_of"))
    age_days = (date.today() - data_as_of).days if data_as_of else None
    freshness_status = "UNKNOWN" if age_days is None else "CURRENT" if age_days <= 90 else "STALE"
    freshness = {"data_as_of": data_as_of, "age_days": age_days, "status": freshness_status}
    completeness = {"score": score, "missing_fields": missing, "evaluable": evaluable, "recommendable": evaluable and freshness_status == "CURRENT"}
    return completeness, freshness


def _candidate_item(row: Any) -> dict[str, Any]:
    region = None
    if row.get("region_id") is not None:
        region = {
            "id": int(row["region_id"]), "region_code": row["region_code"], "name": row["region_name"],
            "parent_region_id": None, "region_type": None, "country_code": None, "station_count": 0,
            "source": {"source_type": row["region_source_type"], "source_url": row["region_source_url"], "source_file": row["region_source_file"], "data_version": row["region_data_version"], "import_batch_id": row["region_import_batch_id"]},
        }
    completeness, freshness = _candidate_quality(row)
    return {
        "id": int(row["id"]), "external_candidate_id": row["external_candidate_id"], "site_name": row["site_name"], "region": region,
        "city": row["city"], "state": row["state"], "latitude": _as_float(row["latitude"]), "longitude": _as_float(row["longitude"]),
        "area_sqm": _as_float(row["area_sqm"]), "parking_spaces": row["parking_spaces"], "electric_capacity_kw": _as_float(row["electric_capacity_kw"]),
        "budget_usd": _as_float(row["budget_usd"]), "traffic_index": _as_float(row["traffic_index"]), "population_density": _as_float(row["population_density"]),
        "planned_open_date": row["planned_open_date"], "data_as_of": row["data_as_of"], "data_status": row["data_status"],
        "lifecycle_status": row["lifecycle_status"], "completeness": completeness, "freshness": freshness, "source": source_info(row),
    }


def _candidate_sql(session: Session) -> str:
    rc = table_columns(session, "region")
    return """SELECT c.id, c.external_candidate_id, c.region_id, c.site_name, c.city, c.state, c.latitude, c.longitude,
        c.area_sqm, c.parking_spaces, c.electric_capacity_kw, c.budget_usd, c.traffic_index, c.population_density,
        c.planned_open_date, c.data_as_of, c.data_status, c.lifecycle_status, c.source_type, c.source_url,
        c.source_file, c.data_version, c.import_batch_id, r.region_code, r.name AS region_name,
        r.source_type AS region_source_type, r.source_url AS region_source_url, """ + _col("r", rc, "source_file") + """ AS region_source_file,
        r.data_version AS region_data_version, """ + _col("r", rc, "import_batch_id") + """ AS region_import_batch_id
        FROM candidate_site c LEFT JOIN region r ON r.id=c.region_id"""


def list_candidates(session: Session, *, region_code: str | None, lifecycle_status: str | None, data_status: str | None, source_type: str | None, candidate_ids: list[int] | None = None, page: int, page_size: int) -> tuple[list[dict[str, Any]], int]:
    conditions = ["c.deleted_at IS NULL"]
    params: dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}
    for value, expression, key in ((region_code, "r.region_code=:region_code", "region_code"), (lifecycle_status, "c.lifecycle_status=:lifecycle_status", "lifecycle_status"), (data_status, "c.data_status=:data_status", "data_status"), (source_type, "c.source_type=:source_type", "source_type")):
        if value:
            conditions.append(expression)
            params[key] = value
    if candidate_ids:
        placeholders = []
        for index, candidate_id in enumerate(candidate_ids):
            key = f"candidate_id_{index}"
            placeholders.append(f":{key}")
            params[key] = candidate_id
        conditions.append(f"c.id IN ({', '.join(placeholders)})")
    where = " AND ".join(conditions)
    total = int(session.execute(text(f"SELECT COUNT(*) FROM candidate_site c LEFT JOIN region r ON r.id=c.region_id WHERE {where}"), params).scalar_one())
    rows = session.execute(text(f"{_candidate_sql(session)} WHERE {where} ORDER BY c.updated_at DESC, c.id DESC LIMIT :limit OFFSET :offset"), params).mappings().all()
    return [_candidate_item(row) for row in rows], total


def get_candidate(session: Session, candidate_id: int) -> dict[str, Any] | None:
    row = session.execute(text(f"{_candidate_sql(session)} WHERE c.id=:candidate_id AND c.deleted_at IS NULL"), {"candidate_id": candidate_id}).mappings().one_or_none()
    if row is None:
        return None
    item = _candidate_item(row)
    nearby: list[dict[str, Any]] = []
    if row["latitude"] is not None and row["longitude"] is not None:
        nearby, _ = list_stations(session, StationQuery(latitude=float(row["latitude"]), longitude=float(row["longitude"]), radius_km=25, page=1, page_size=10))
    policies = session.execute(text("""SELECT id, policy_code, policy_version, title, policy_type, applicant_type,
        condition_key, condition_operator, condition_value, required_materials, effective_from, effective_to,
        application_deadline, source_type, source_url, source_file, data_version, import_batch_id
        FROM policy_condition WHERE deleted_at IS NULL AND (:region_id IS NULL OR region_id=:region_id)
        ORDER BY effective_from DESC, id DESC LIMIT 50"""), {"region_id": row["region_id"]}).mappings().all()
    policy_items = [dict(policy) for policy in policies]
    item.update({
        "nearby_stations": nearby,
        "policies": policy_items,
        "related": {"nearby_station_count": len(nearby), "policy_count": len(policy_items), "region_href": f"/regions/{row['region_code']}" if row["region_code"] else ""},
    })
    return item


def _resolve_region_id(session: Session, payload: CandidateWrite, current_region_id: int | None = None) -> int | None:
    if payload.region_id:
        exists = session.execute(text("SELECT COUNT(*) FROM region WHERE id=:id"), {"id": payload.region_id}).scalar_one()
        if not exists:
            raise LookupError("region not found")
        return payload.region_id
    if payload.region_code:
        result = session.execute(text("SELECT id FROM region WHERE region_code=:code ORDER BY data_version DESC LIMIT 1"), {"code": payload.region_code}).scalar_one_or_none()
        if result is None:
            raise LookupError("region not found")
        return int(result)
    return current_region_id


def _validate_recommendation(item: dict[str, Any], lifecycle_status: str) -> None:
    if lifecycle_status == "RECOMMENDED" and not item["completeness"]["recommendable"]:
        raise ValueError("candidate is not evaluable or data is stale; recommendation is blocked")


def create_candidate(session: Session, payload: CandidateWrite, user: UserContext) -> dict[str, Any]:
    if not payload.site_name:
        raise ValueError("site_name is required")
    region_id = _resolve_region_id(session, payload)
    region_code = payload.region_code or session.execute(text("SELECT region_code FROM region WHERE id=:id"), {"id": region_id}).scalar_one_or_none()
    enforce_data_scope(user, dataset_type=payload.source_type, write=True, region_code=region_code)
    now = _now()
    data_version = payload.data_version or date.today().isoformat()
    external_id = payload.external_candidate_id or f"CAND-{uuid4().hex[:12].upper()}"
    data_as_of = payload.data_as_of or date.today()
    values = payload.model_dump()
    values.update({"region_id": region_id, "external_candidate_id": external_id, "data_version": data_version, "data_as_of": data_as_of})
    preview = {**values, "id": 0, "source": {"source_type": payload.source_type, "data_version": data_version}, "region_id": region_id}
    completeness, freshness = _candidate_quality(preview)
    _validate_recommendation({"completeness": completeness}, payload.lifecycle_status)
    data_status = freshness["status"]
    session.execute(text("""INSERT INTO candidate_site
        (external_candidate_id, region_id, site_name, city, state, latitude, longitude, area_sqm, parking_spaces,
         electric_capacity_kw, budget_usd, traffic_index, population_density, planned_open_date, data_as_of,
         data_status, lifecycle_status, source_type, source_url, source_file, data_version, import_batch_id,
         created_by, created_at, updated_at)
        VALUES (:external_candidate_id, :region_id, :site_name, :city, :state, :latitude, :longitude, :area_sqm,
         :parking_spaces, :electric_capacity_kw, :budget_usd, :traffic_index, :population_density, :planned_open_date,
         :data_as_of, :data_status, :lifecycle_status, :source_type, :source_url, :source_file, :data_version,
         NULL, :created_by, :created_at, :updated_at)"""), {**values, "data_status": data_status, "created_by": user.user_id, "created_at": now, "updated_at": now})
    candidate_id = int(session.execute(text("SELECT LAST_INSERT_ID()")).scalar_one())
    record_audit_event(session, action="CANDIDATE_CREATED", resource_type="candidate_site", resource_id=str(candidate_id), actor_user_id=user.user_id, after_state={"lifecycle_status": payload.lifecycle_status, "source_type": payload.source_type}, commit=True)
    return get_candidate(session, candidate_id)  # type: ignore[return-value]


def update_candidate(session: Session, candidate_id: int, payload: CandidateWrite, user: UserContext) -> dict[str, Any]:
    current = get_candidate(session, candidate_id)
    if current is None:
        raise LookupError("candidate not found")
    current_source_type = current["source"].source_type
    current_region_code = current["region"]["region_code"] if current["region"] else None
    if payload.source_type != current_source_type:
        enforce_data_scope(user, dataset_type=payload.source_type, write=True, region_code=payload.region_code or current_region_code)
    else:
        enforce_data_scope(user, dataset_type=current_source_type, write=True, region_code=payload.region_code or current_region_code)
    values = payload.model_dump(exclude_unset=True)
    region_id = _resolve_region_id(session, payload, current["region"]["id"] if current["region"] else None)
    values.pop("region_code", None)
    values["region_id"] = region_id
    values.pop("external_candidate_id", None)
    values.pop("source_type", None)
    values.pop("source_url", None)
    values.pop("source_file", None)
    if not values:
        raise ValueError("at least one candidate field is required")
    merged = dict(current)
    merged.update(values)
    if "data_as_of" not in merged or merged["data_as_of"] is None:
        merged["data_as_of"] = date.today()
    completeness, freshness = _candidate_quality(merged)
    target_status = values.get("lifecycle_status", current["lifecycle_status"])
    _validate_recommendation({"completeness": completeness}, target_status)
    values["data_status"] = freshness["status"]
    values["updated_at"] = _now()
    assignments = ", ".join(f"{key}=:{key}" for key in values if key in {"site_name", "region_id", "city", "state", "latitude", "longitude", "area_sqm", "parking_spaces", "electric_capacity_kw", "budget_usd", "traffic_index", "population_density", "planned_open_date", "data_as_of", "data_status", "lifecycle_status", "updated_at"})
    params = {key: value for key, value in values.items() if key in assignments}
    params["id"] = candidate_id
    session.execute(text(f"UPDATE candidate_site SET {assignments} WHERE id=:id"), params)
    record_audit_event(session, action="CANDIDATE_UPDATED", resource_type="candidate_site", resource_id=str(candidate_id), actor_user_id=user.user_id, after_state={"fields": list(values), "lifecycle_status": target_status}, commit=True)
    return get_candidate(session, candidate_id)  # type: ignore[return-value]


def update_candidate_status(session: Session, candidate_id: int, lifecycle_status: str, reason: str | None, user: UserContext) -> dict[str, Any]:
    current = get_candidate(session, candidate_id)
    if current is None:
        raise LookupError("candidate not found")
    enforce_data_scope(user, dataset_type=current["source"].source_type, write=True, region_code=current["region"]["region_code"] if current["region"] else None)
    _validate_recommendation(current, lifecycle_status)
    session.execute(text("UPDATE candidate_site SET lifecycle_status=:status, updated_at=:updated_at WHERE id=:id"), {"status": lifecycle_status, "updated_at": _now(), "id": candidate_id})
    record_audit_event(session, action="CANDIDATE_STATUS_CHANGED", resource_type="candidate_site", resource_id=str(candidate_id), actor_user_id=user.user_id, after_state={"lifecycle_status": lifecycle_status, "reason": reason}, commit=True)
    return get_candidate(session, candidate_id)  # type: ignore[return-value]


def delete_candidate(session: Session, candidate_id: int, user: UserContext) -> None:
    current = get_candidate(session, candidate_id)
    if current is None:
        raise LookupError("candidate not found")
    enforce_data_scope(user, dataset_type=current["source"].source_type, write=True, region_code=current["region"]["region_code"] if current["region"] else None)
    session.execute(text("UPDATE candidate_site SET deleted_at=:deleted_at, updated_at=:updated_at WHERE id=:id"), {"deleted_at": _now(), "updated_at": _now(), "id": candidate_id})
    record_audit_event(session, action="CANDIDATE_DELETED", resource_type="candidate_site", resource_id=str(candidate_id), actor_user_id=user.user_id, severity="WARNING", commit=True)
