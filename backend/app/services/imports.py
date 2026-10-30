from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.errors import AppError
from app.schemas.imports import (
    DatasetType,
    ImportBatchDetail,
    ImportBatchListResponse,
    ImportBatchSummary,
    ImportConfirmRequest,
    ImportFieldDefinition,
    ImportPreviewResponse,
    ImportValidationError,
)
from app.services.auth import UserContext, _redact, enforce_data_scope, record_audit_event, require_permission


FIELD_DEFINITIONS: dict[str, list[ImportFieldDefinition]] = {
    "stations": [
        ImportFieldDefinition(key="external_station_id", label="外部站点 ID", kind="text", required=True, hint="稳定站点标识"),
        ImportFieldDefinition(key="station_name", label="站点名称", kind="text", required=True, hint="站点展示名称"),
        ImportFieldDefinition(key="latitude", label="纬度", kind="number", required=True, hint="-90 到 90"),
        ImportFieldDefinition(key="longitude", label="经度", kind="number", required=True, hint="-180 到 180"),
        ImportFieldDefinition(key="station_status", label="站点状态", kind="text", required=True, hint="站点运营状态"),
        ImportFieldDefinition(key="access_type", label="访问类型", kind="text", required=True, hint="PUBLIC 或 PRIVATE"),
        ImportFieldDefinition(key="data_version", label="数据版本", kind="text", required=True, hint="版本号"),
    ],
    "connectors": [
        ImportFieldDefinition(key="station_external_id", label="外部站点 ID", kind="text", required=True, hint="已存在站点标识"),
        ImportFieldDefinition(key="connector_type", label="连接器类型", kind="text", required=True, hint="CCS、CHAdeMO 等"),
        ImportFieldDefinition(key="quantity", label="数量", kind="number", required=True, hint="非负整数"),
        ImportFieldDefinition(key="power_kw", label="功率（kW）", kind="number", hint="非负数"),
        ImportFieldDefinition(key="connector_status", label="连接器状态", kind="text", hint="可用或维护中"),
        ImportFieldDefinition(key="data_version", label="数据版本", kind="text", required=True, hint="版本号"),
    ],
    "metrics": [
        ImportFieldDefinition(key="station_external_id", label="外部站点 ID", kind="text", required=True, hint="已存在站点标识"),
        ImportFieldDefinition(key="metric_date", label="指标日期", kind="date", required=True, hint="YYYY-MM-DD"),
        ImportFieldDefinition(key="metric_hour", label="小时", kind="number", hint="0 到 23"),
        ImportFieldDefinition(key="charging_sessions", label="充电会话数", kind="number", hint="非负整数"),
        ImportFieldDefinition(key="energy_kwh", label="能耗（kWh）", kind="number", hint="非负数"),
        ImportFieldDefinition(key="peak_power_kw", label="峰值功率（kW）", kind="number", hint="非负数"),
        ImportFieldDefinition(key="occupancy_rate", label="利用率", kind="number", hint="0 到 1 或百分比"),
        ImportFieldDefinition(key="data_as_of", label="数据截至日期", kind="date", hint="YYYY-MM-DD"),
    ],
    "faults": [
        ImportFieldDefinition(key="station_external_id", label="外部站点 ID", kind="text", required=True, hint="已存在站点标识"),
        ImportFieldDefinition(key="fault_type", label="故障类型", kind="text", required=True, hint="故障分类"),
        ImportFieldDefinition(key="severity", label="严重等级", kind="text", required=True, hint="LOW 到 CRITICAL"),
        ImportFieldDefinition(key="started_at", label="开始时间", kind="datetime", required=True, hint="ISO 8601 时间"),
        ImportFieldDefinition(key="recovered_at", label="恢复时间", kind="datetime", hint="可为空"),
        ImportFieldDefinition(key="status", label="状态", kind="text", hint="OPEN、RECOVERED、CLOSED"),
    ],
    "candidates": [
        ImportFieldDefinition(key="candidate_site_external_id", label="外部候选点 ID", kind="text", required=True, hint="稳定候选点标识"),
        ImportFieldDefinition(key="site_name", label="候选点名称", kind="text", required=True, hint="规划名称"),
        ImportFieldDefinition(key="region_code", label="区域编码", kind="text", required=True, hint="例如 CA-06037"),
        ImportFieldDefinition(key="latitude", label="纬度", kind="number", required=True, hint="-90 到 90"),
        ImportFieldDefinition(key="longitude", label="经度", kind="number", required=True, hint="-180 到 180"),
        ImportFieldDefinition(key="budget_usd", label="预算（USD）", kind="number", hint="非负数"),
        ImportFieldDefinition(key="data_as_of", label="数据截至日期", kind="date", hint="YYYY-MM-DD"),
    ],
    "expansion": [
        ImportFieldDefinition(key="case_external_id", label="案例 ID", kind="text", required=True, hint="稳定案例标识"),
        ImportFieldDefinition(key="station_external_id", label="外部站点 ID", kind="text", required=True, hint="已存在站点标识"),
        ImportFieldDefinition(key="case_date", label="案例日期", kind="date", required=True, hint="YYYY-MM-DD"),
        ImportFieldDefinition(key="peak_occupancy_rate", label="峰值利用率", kind="number", hint="0 到 1 或百分比"),
        ImportFieldDefinition(key="requested_budget_usd", label="申请预算（USD）", kind="number", hint="非负数"),
        ImportFieldDefinition(key="proposed_fast_connectors", label="建议快充数", kind="number", hint="非负整数"),
        ImportFieldDefinition(key="priority", label="优先级", kind="text", required=True, hint="LOW 到 CRITICAL"),
    ],
}


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _number(value: Any, *, integer: bool = False, non_negative: bool = True) -> int | float | None:
    value = _text(value)
    if not value:
        return None
    number = float(value.replace(",", ""))
    if non_negative and number < 0:
        raise ValueError("数值不能为负数")
    if integer:
        if not number.is_integer():
            raise ValueError("必须是整数")
        return int(number)
    return number


def _date(value: Any) -> date | None:
    value = _text(value)
    if not value:
        return None
    return date.fromisoformat(value[:10])


def _datetime(value: Any) -> datetime | None:
    value = _text(value)
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def _parse_content(file_name: str, content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    try:
        text_content = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("文件必须使用 UTF-8 编码") from exc
    extension = file_name.lower().rsplit(".", 1)[-1] if "." in file_name else "csv"
    if extension in {"json", "geojson"}:
        payload = json.loads(text_content)
        if isinstance(payload, dict) and isinstance(payload.get("features"), list):
            rows = []
            for feature in payload["features"]:
                item = dict(feature.get("properties") or {})
                coordinates = ((feature.get("geometry") or {}).get("coordinates") or [])
                if len(coordinates) >= 2:
                    item.setdefault("longitude", coordinates[0])
                    item.setdefault("latitude", coordinates[1])
                rows.append(item)
        elif isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            rows = [payload]
        else:
            raise ValueError("JSON 顶层必须是数组、对象或 GeoJSON FeatureCollection")
        normalized = [{str(key): _text(value) for key, value in row.items()} for row in rows if isinstance(row, dict)]
        headers = list(dict.fromkeys(key for row in normalized for key in row))
        return headers, normalized
    reader = csv.DictReader(io.StringIO(text_content))
    headers = [str(item).strip() for item in (reader.fieldnames or [])]
    if not headers:
        raise ValueError("CSV 文件缺少首行字段名")
    return headers, [{key: _text(value) for key, value in row.items() if key is not None} for row in reader]


def _auto_mapping(dataset_type: DatasetType, headers: list[str]) -> dict[str, str]:
    normalized = {header.lower().replace("-", "_").replace(" ", "_"): header for header in headers}
    return {field.key: normalized[field.key] for field in FIELD_DEFINITIONS[dataset_type] if field.key in normalized}


def _validate(dataset_type: DatasetType, rows: list[dict[str, Any]], mapping: dict[str, str]) -> list[ImportValidationError]:
    errors: list[ImportValidationError] = []
    fields = FIELD_DEFINITIONS[dataset_type]
    for field in fields:
        if field.required and not mapping.get(field.key):
            errors.append(ImportValidationError(row=0, field=field.label, level="error", message="必填字段尚未映射", suggestion=f"请选择对应的“{field.label}”源字段"))
    for row_index, row in enumerate(rows, start=2):
        for field in fields:
            value = _text(row.get(mapping.get(field.key, ""))) if mapping.get(field.key) else ""
            if field.required and not value:
                errors.append(ImportValidationError(row=row_index, field=field.label, level="error", message="必填值为空", suggestion="补充字段值后重新上传"))
                continue
            if not value:
                continue
            try:
                if field.kind == "number":
                    _number(value, non_negative=field.key not in {"latitude", "longitude"})
                elif field.kind == "date":
                    _date(value)
                elif field.kind == "datetime":
                    _datetime(value)
            except (TypeError, ValueError) as exc:
                errors.append(ImportValidationError(row=row_index, field=field.label, level="error", message=str(exc), suggestion=f"按 {field.hint} 修复后重试"))
            if field.key in {"latitude", "longitude"}:
                try:
                    number = float(value)
                    low, high = (-90, 90) if field.key == "latitude" else (-180, 180)
                    if not low <= number <= high:
                        errors.append(ImportValidationError(row=row_index, field=field.label, level="error", message="坐标超出范围", suggestion=f"请输入 {low} 到 {high} 之间的数值"))
                except ValueError:
                    pass
    return errors[:500]


def preview_upload(*, dataset_type: DatasetType, file_name: str, content: bytes) -> ImportPreviewResponse:
    headers, rows = _parse_content(file_name, content)
    mapping = _auto_mapping(dataset_type, headers)
    return ImportPreviewResponse(dataset_type=dataset_type, file_name=file_name, headers=headers, rows=rows[:5000], mapping=mapping, fields=FIELD_DEFINITIONS[dataset_type], errors=_validate(dataset_type, rows[:5000], mapping), total_rows=len(rows))


def _target_row(request: ImportConfirmRequest, row: dict[str, Any]) -> dict[str, str]:
    return {field.key: _text(row.get(request.mapping.get(field.key, field.key))) for field in FIELD_DEFINITIONS[request.dataset_type]}


def _station_id(session: Session, external_id: str, data_version: str) -> int:
    value = int(float(external_id))
    row = session.execute(text("SELECT id FROM charging_station WHERE external_station_id=:external_id AND data_version=:data_version AND deleted_at IS NULL LIMIT 1"), {"external_id": value, "data_version": data_version}).scalar_one_or_none()
    if row is None:
        row = session.execute(text("SELECT id FROM charging_station WHERE external_station_id=:external_id ORDER BY id DESC LIMIT 1"), {"external_id": value}).scalar_one_or_none()
    if row is None:
        raise ValueError(f"找不到外部站点 {external_id}")
    return int(row)


def _region_id(session: Session, region_code: str | None) -> int | None:
    if not region_code:
        return None
    return session.execute(text("SELECT id FROM region WHERE region_code=:region_code ORDER BY id DESC LIMIT 1"), {"region_code": region_code}).scalar_one_or_none()


def _operator_id(session: Session, operator_name: str | None, data_version: str, batch_id: int) -> int | None:
    if not operator_name:
        return None
    found = session.execute(text("SELECT id FROM `operator` WHERE operator_name=:name AND data_version=:version LIMIT 1"), {"name": operator_name, "version": data_version}).scalar_one_or_none()
    if found:
        return int(found)
    now = _now()
    session.execute(text("INSERT INTO `operator` (operator_name, source_type, data_version, import_batch_id, created_at, updated_at) VALUES (:name, 'user_upload', :version, :batch_id, :now, :now)"), {"name": operator_name, "version": data_version, "batch_id": batch_id, "now": now})
    return int(session.execute(text("SELECT LAST_INSERT_ID()")).scalar_one())


def _insert_row(session: Session, dataset_type: DatasetType, row: dict[str, str], *, batch_id: int, file_name: str, data_version: str, user: UserContext) -> None:
    now = _now()
    source = {"source_type": "user_upload", "source_url": "", "source_file": file_name[:500], "data_version": data_version, "import_batch_id": batch_id, "batch_id": batch_id, "created_at": now, "updated_at": now}
    if dataset_type == "stations":
        external_id = int(float(row["external_station_id"]))
        # The legacy public station table requires a region FK while the
        # upload template historically omitted region_code.  ChargeOps' public
        # snapshot is California, so default that field for this compatibility
        # path and still honor an explicitly supplied region.
        region_id = _region_id(session, row.get("region_code") or "CA")
        operator_id = _operator_id(session, row.get("operator_name"), data_version, batch_id)
        session.execute(text("""INSERT INTO charging_station
            (external_station_id, external_station_key, region_id, operator_id, station_name, street_address, city, state, zip_code, country_code, latitude, longitude, station_status, access_type, facility_type, total_connector_count, total_power_kw, source_type, source_url, source_file, data_version, import_batch_id, created_at, updated_at)
            VALUES (:external_id, :external_key, :region_id, :operator_id, :station_name, :street_address, :city, :state, :zip_code, :country_code, :latitude, :longitude, :station_status, :access_type, :facility_type, :connector_count, :power_kw, 'user_upload', :source_url, :source_file, :data_version, :batch_id, :created_at, :updated_at)
            ON DUPLICATE KEY UPDATE station_name=VALUES(station_name), latitude=VALUES(latitude), longitude=VALUES(longitude), station_status=VALUES(station_status), access_type=VALUES(access_type), import_batch_id=VALUES(import_batch_id), updated_at=VALUES(updated_at)"""), {**source, "external_id": external_id, "external_key": row.get("external_station_key") or None, "region_id": region_id, "operator_id": operator_id, "station_name": row["station_name"], "street_address": row.get("street_address") or None, "city": row.get("city") or None, "state": row.get("state") or None, "zip_code": row.get("zip_code") or None, "country_code": row.get("country_code") or None, "latitude": _number(row.get("latitude"), non_negative=False), "longitude": _number(row.get("longitude"), non_negative=False), "station_status": row["station_status"], "access_type": row["access_type"], "facility_type": row.get("facility_type") or None, "connector_count": _number(row.get("total_connector_count"), integer=True) or 0, "power_kw": _number(row.get("total_power_kw"))})
        return
    if dataset_type == "connectors":
        station_id = _station_id(session, row["station_external_id"], data_version)
        session.execute(text("""INSERT INTO charging_connector (station_id, connector_type, quantity, power_kw, connector_status, source_type, source_url, source_file, data_version, import_batch_id, created_at, updated_at)
            VALUES (:station_id, :connector_type, :quantity, :power_kw, :connector_status, 'user_upload', :source_url, :source_file, :data_version, :batch_id, :created_at, :updated_at)
            ON DUPLICATE KEY UPDATE quantity=VALUES(quantity), power_kw=VALUES(power_kw), connector_status=VALUES(connector_status), import_batch_id=VALUES(import_batch_id), updated_at=VALUES(updated_at)"""), {**source, "station_id": station_id, "connector_type": row["connector_type"], "quantity": _number(row["quantity"], integer=True), "power_kw": _number(row.get("power_kw")), "connector_status": row.get("connector_status") or "UNKNOWN"})
        return
    if dataset_type == "metrics":
        station_id = _station_id(session, row["station_external_id"], data_version)
        session.execute(text("""INSERT INTO station_operation_metric (station_id, metric_date, metric_hour, timezone, charging_sessions, energy_kwh, peak_power_kw, occupancy_rate, avg_session_minutes, data_as_of, source_type, source_url, source_file, data_version, import_batch_id, created_at, updated_at)
            VALUES (:station_id, :metric_date, :metric_hour, 'UTC', :charging_sessions, :energy_kwh, :peak_power_kw, :occupancy_rate, :avg_session_minutes, :data_as_of, 'user_upload', :source_url, :source_file, :data_version, :batch_id, :created_at, :updated_at)
            ON DUPLICATE KEY UPDATE charging_sessions=VALUES(charging_sessions), energy_kwh=VALUES(energy_kwh), peak_power_kw=VALUES(peak_power_kw), occupancy_rate=VALUES(occupancy_rate), import_batch_id=VALUES(import_batch_id), updated_at=VALUES(updated_at)"""), {**source, "station_id": station_id, "metric_date": _date(row["metric_date"]), "metric_hour": _number(row.get("metric_hour"), integer=True), "charging_sessions": _number(row.get("charging_sessions"), integer=True), "energy_kwh": _number(row.get("energy_kwh")), "peak_power_kw": _number(row.get("peak_power_kw")), "occupancy_rate": _number(row.get("occupancy_rate"), non_negative=False), "avg_session_minutes": _number(row.get("avg_session_minutes")), "data_as_of": _date(row.get("data_as_of"))})
        return
    if dataset_type == "faults":
        station_id = _station_id(session, row["station_external_id"], data_version)
        session.execute(text("""INSERT INTO station_fault_event (station_id, external_fault_id, fault_type, severity, started_at, recovered_at, affected_connectors, root_cause, status, data_as_of, source_type, source_url, source_file, data_version, import_batch_id, created_at, updated_at)
            VALUES (:station_id, :external_fault_id, :fault_type, :severity, :started_at, :recovered_at, :affected_connectors, :root_cause, :status, :data_as_of, 'user_upload', :source_url, :source_file, :data_version, :batch_id, :created_at, :updated_at)
            ON DUPLICATE KEY UPDATE severity=VALUES(severity), recovered_at=VALUES(recovered_at), status=VALUES(status), import_batch_id=VALUES(import_batch_id), updated_at=VALUES(updated_at)"""), {**source, "station_id": station_id, "external_fault_id": row.get("external_fault_id") or None, "fault_type": row["fault_type"], "severity": row["severity"], "started_at": _datetime(row["started_at"]), "recovered_at": _datetime(row.get("recovered_at")), "affected_connectors": _number(row.get("affected_connectors"), integer=True), "root_cause": row.get("root_cause") or None, "status": row.get("status") or "OPEN", "data_as_of": _date(row.get("data_as_of"))})
        return
    if dataset_type == "candidates":
        session.execute(text("""INSERT INTO candidate_site (external_candidate_id, region_id, site_name, city, state, latitude, longitude, area_sqm, parking_spaces, electric_capacity_kw, budget_usd, traffic_index, population_density, planned_open_date, data_as_of, data_status, lifecycle_status, source_type, source_url, source_file, data_version, import_batch_id, created_by, created_at, updated_at)
            VALUES (:external_id, :region_id, :site_name, :city, :state, :latitude, :longitude, :area_sqm, :parking_spaces, :capacity, :budget, :traffic, :population, :planned_open_date, :data_as_of, 'CURRENT', 'DRAFT', 'user_upload', :source_url, :source_file, :data_version, :batch_id, :created_by, :created_at, :updated_at)
            ON DUPLICATE KEY UPDATE site_name=VALUES(site_name), latitude=VALUES(latitude), longitude=VALUES(longitude), budget_usd=VALUES(budget_usd), import_batch_id=VALUES(import_batch_id), updated_at=VALUES(updated_at)"""), {**source, "external_id": row["candidate_site_external_id"], "region_id": _region_id(session, row.get("region_code")), "site_name": row["site_name"], "city": row.get("city") or None, "state": row.get("state") or None, "latitude": _number(row.get("latitude"), non_negative=False), "longitude": _number(row.get("longitude"), non_negative=False), "area_sqm": _number(row.get("area_sqm")), "parking_spaces": _number(row.get("parking_spaces"), integer=True), "capacity": _number(row.get("electric_capacity_kw")), "budget": _number(row.get("budget_usd")), "traffic": _number(row.get("traffic_index"), non_negative=False), "population": _number(row.get("population_density")), "planned_open_date": _date(row.get("planned_open_date")), "data_as_of": _date(row.get("data_as_of")), "created_by": user.user_id})
        return
    station_id = _station_id(session, row["station_external_id"], data_version)
    session.execute(text("""INSERT INTO expansion_plan (external_case_id, station_id, existing_fast_connectors, existing_slow_connectors, peak_occupancy_rate, fault_count_30d, available_capacity_kw, proposed_fast_connectors, proposed_slow_connectors, requested_budget_usd, priority, preconditions, confirmation_status, source_type, source_url, source_file, data_version, import_batch_id, created_at, updated_at)
        VALUES (:external_id, :station_id, :existing_fast, :existing_slow, :peak_occupancy, :fault_count, :capacity, :proposed_fast, :proposed_slow, :budget, :priority, :preconditions, 'WAITING_CONFIRMATION', 'user_upload', :source_url, :source_file, :data_version, :batch_id, :created_at, :updated_at)
        ON DUPLICATE KEY UPDATE priority=VALUES(priority), requested_budget_usd=VALUES(requested_budget_usd), import_batch_id=VALUES(import_batch_id), updated_at=VALUES(updated_at)"""), {**source, "external_id": row.get("case_external_id") or None, "station_id": station_id, "existing_fast": _number(row.get("existing_fast_connectors"), integer=True), "existing_slow": _number(row.get("existing_slow_connectors"), integer=True), "peak_occupancy": _number(row.get("peak_occupancy_rate"), non_negative=False), "fault_count": _number(row.get("fault_count_30d"), integer=True), "capacity": _number(row.get("available_capacity_kw")), "proposed_fast": _number(row.get("proposed_fast_connectors"), integer=True), "proposed_slow": _number(row.get("proposed_slow_connectors"), integer=True), "budget": _number(row.get("requested_budget_usd")), "priority": row.get("priority") or "MEDIUM", "preconditions": json.dumps([row.get("preconditions")], ensure_ascii=False) if row.get("preconditions") else None})


def _summary(row: Any) -> ImportBatchSummary:
    return ImportBatchSummary(id=int(row["id"]), batch_key=row["batch_key"], dataset_type=row["dataset_type"], source_type=row["source_type"], source_file=row.get("source_file"), source_sha256=row.get("source_sha256"), data_version=row["data_version"], row_count=int(row["row_count"] or 0), success_count=int(row["success_count"] or 0), failed_count=int(row["failed_count"] or 0), skipped_count=int(row["skipped_count"] or 0), status=row["status"], rollback_status=row["rollback_status"], created_at=row["created_at"], completed_at=row.get("completed_at"))


def import_rows(session: Session, user: UserContext, request: ImportConfirmRequest) -> ImportBatchDetail:
    require_permission(user, "import.write", session=session)
    enforce_data_scope(user, dataset_type="user_upload", write=True)
    now = _now()
    batch_key = f"upload-{uuid4()}"
    source_sha256 = hashlib.sha256(json.dumps(request.rows, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    region_code = next((_text(row.get(request.mapping.get("region_code", "region_code"))) for row in request.rows if _text(row.get(request.mapping.get("region_code", "region_code")))), "*")
    session.execute(text("""INSERT INTO import_batch (batch_key, dataset_type, source_type, source_url, source_file, source_sha256, region_code, data_version, row_count, status, rollback_status, created_by, created_at)
        VALUES (:batch_key, :dataset_type, 'user_upload', :source_url, :source_file, :source_sha256, :region_code, :data_version, :row_count, 'PENDING', 'NOT_REQUESTED', :created_by, :created_at)"""), {"batch_key": batch_key, "dataset_type": request.dataset_type, "source_url": "", "source_file": request.file_name, "source_sha256": source_sha256, "region_code": region_code, "data_version": request.data_version, "row_count": len(request.rows), "created_by": user.user_id, "created_at": now})
    batch_id = int(session.execute(text("SELECT LAST_INSERT_ID()")).scalar_one())
    errors: list[dict[str, Any]] = []
    success = 0
    for row_number, raw_row in enumerate(request.rows, start=2):
        target = _target_row(request, raw_row)
        try:
            with session.begin_nested():
                row_errors = _validate(request.dataset_type, [raw_row], request.mapping)
                if row_errors:
                    raise ValueError(row_errors[0].message)
                _insert_row(session, request.dataset_type, target, batch_id=batch_id, file_name=request.file_name, data_version=request.data_version, user=user)
            success += 1
        except Exception as exc:
            error = {"row": row_number, "field": None, "level": "error", "message": str(exc)[:1000], "suggestion": "修复该行后重新上传"}
            errors.append(error)
            session.execute(text("""INSERT INTO import_row_error (import_batch_id, source_file, source_row_number, field_name, error_code, error_message, raw_payload, created_at)
                VALUES (:batch_id, :source_file, :row_number, NULL, 'IMPORT_ROW_FAILED', :message, :raw_payload, :created_at)"""), {"batch_id": batch_id, "source_file": request.file_name, "row_number": row_number, "message": str(exc)[:1000], "raw_payload": json.dumps(_redact(raw_row), ensure_ascii=False, default=str), "created_at": _now()})
    status = "IMPORTED" if not errors else ("FAILED" if not success else "PARTIAL")
    session.execute(text("UPDATE import_batch SET success_count=:success, failed_count=:failed, status=:status, completed_at=:completed_at WHERE id=:id"), {"success": success, "failed": len(errors), "status": status, "completed_at": _now(), "id": batch_id})
    record_audit_event(session, action="IMPORT_BATCH_COMPLETED", resource_type="import_batch", resource_id=str(batch_id), actor_user_id=user.user_id, metadata={"import_batch_id": batch_id, "dataset_type": request.dataset_type, "success_count": success, "failed_count": len(errors)})
    return get_batch(session, batch_id, user=user)  # type: ignore[return-value]


def list_batches(session: Session, user: UserContext, *, page: int = 1, page_size: int = 25) -> ImportBatchListResponse:
    require_permission(user, "import.read", session=session)
    where = "" if "SYSTEM_ADMIN" in user.role_codes else " WHERE created_by=:user_id"
    params: dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}
    if where:
        params["user_id"] = user.user_id
    rows = session.execute(text(f"SELECT * FROM import_batch{where} ORDER BY id DESC LIMIT :limit OFFSET :offset"), params).mappings().all()
    total = int(session.execute(text(f"SELECT COUNT(*) FROM import_batch{where}"), {key: value for key, value in params.items() if key == "user_id"}).scalar_one())
    return ImportBatchListResponse(items=[_summary(row) for row in rows], page={"page": page, "page_size": page_size, "total": total, "has_next": page * page_size < total})


def get_batch(session: Session, batch_id: int, *, user: UserContext) -> ImportBatchDetail | None:
    require_permission(user, "import.read", session=session)
    row = session.execute(text("SELECT * FROM import_batch WHERE id=:id"), {"id": batch_id}).mappings().one_or_none()
    if row is None or ("SYSTEM_ADMIN" not in user.role_codes and row.get("created_by") != user.user_id):
        return None
    errors = session.execute(text("SELECT source_row_number AS `row`, field_name AS field, error_code, error_message AS message, raw_payload FROM import_row_error WHERE import_batch_id=:id ORDER BY id"), {"id": batch_id}).mappings().all()
    return ImportBatchDetail(**_summary(row).model_dump(), errors=[dict(item) for item in errors])


def rollback_batch(session: Session, batch_id: int, user: UserContext) -> ImportBatchDetail:
    require_permission(user, "import.write", session=session)
    enforce_data_scope(user, dataset_type="user_upload", write=True)
    row = session.execute(text("SELECT * FROM import_batch WHERE id=:id"), {"id": batch_id}).mappings().one_or_none()
    if row is None or ("SYSTEM_ADMIN" not in user.role_codes and row.get("created_by") != user.user_id):
        raise AppError("IMPORT_BATCH_NOT_FOUND", "导入批次不存在", status_code=404)
    for table in ("import_row_error", "expansion_plan", "station_fault_event", "station_operation_metric", "charging_connector", "charging_station", "candidate_site", "operator", "region"):
        session.execute(text(f"DELETE FROM `{table}` WHERE import_batch_id=:batch_id"), {"batch_id": batch_id})
    session.execute(text("UPDATE import_batch SET status='ROLLED_BACK', rollback_status='ROLLED_BACK', completed_at=:completed_at WHERE id=:id"), {"completed_at": _now(), "id": batch_id})
    record_audit_event(session, action="IMPORT_BATCH_ROLLED_BACK", resource_type="import_batch", resource_id=str(batch_id), actor_user_id=user.user_id, metadata={"import_batch_id": batch_id})
    return get_batch(session, batch_id, user=user)  # type: ignore[return-value]

