"""Import cleaned public and synthetic ChargeOps data with batch tracking."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pymysql


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
PUBLIC_DEFAULT = PROJECT_ROOT / "data" / "processed" / "afdc_electric_stations_ca_2026-10-29_cleaned.csv"
PUBLIC_MANIFEST = PROJECT_ROOT / "data" / "manifests" / "afdc_electric_stations_ca_2026-10-29_cleaning_manifest.json"
SYNTHETIC_DIR = PROJECT_ROOT / "data" / "raw" / "synthetic"
SYNTHETIC_MANIFEST = PROJECT_ROOT / "data" / "manifests" / "synthetic_demo_2026-10-29.json"
SOURCE_TYPE_VALUES = {"public", "user_upload", "synthetic", "agent"}
SYNTHETIC_VERSION = "2026-10-29"


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("'\"")
    values.update({key: value for key, value in os.environ.items() if key not in values})
    return values


def connect(env: dict[str, str], autocommit: bool = False):
    parsed = urllib.parse.urlparse(env["MYSQL_DSN"].replace("mysql+pymysql://", "mysql://", 1))
    return pymysql.connect(
        host=parsed.hostname,
        port=parsed.port or 3306,
        user=urllib.parse.unquote(parsed.username or ""),
        password=urllib.parse.unquote(parsed.password or ""),
        database=parsed.path.lstrip("/"),
        charset="utf8mb4",
        autocommit=autocommit,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def as_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    return int(float(value))


def as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def as_date(value: Any) -> str | None:
    value = str(value or "")
    return value[:10] if len(value) >= 10 and value[4] == "-" and value[7] == "-" else None


def as_mysql_datetime(value: Any) -> str | None:
    value = str(value or "").strip()
    if not value:
        return None
    return value.replace("T", " ").replace("Z", "")[:19]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def ensure_region(cursor, code: str, name: str, source_type: str, source_url: str, batch_id: int, version: str) -> int:
    cursor.execute("SELECT id FROM region WHERE region_code=%s LIMIT 1", (code,))
    row = cursor.fetchone()
    if row:
        return int(row[0])
    timestamp = now_utc()
    cursor.execute(
        """INSERT INTO region(region_code,name,source_type,source_url,data_version,import_batch_id,created_at,updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (code, name, source_type, source_url, version, batch_id, timestamp, timestamp),
    )
    return int(cursor.lastrowid)


def ensure_operator(cursor, name: str, source_type: str, source_url: str, batch_id: int, version: str) -> int:
    cursor.execute("SELECT id FROM `operator` WHERE operator_name=%s AND data_version=%s LIMIT 1", (name, version))
    row = cursor.fetchone()
    if row:
        return int(row[0])
    timestamp = now_utc()
    cursor.execute(
        """INSERT INTO `operator`(operator_name,source_type,source_url,data_version,import_batch_id,created_at,updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (name, source_type, source_url, version, batch_id, timestamp, timestamp),
    )
    return int(cursor.lastrowid)


def ensure_batch(
    cursor,
    batch_key: str,
    dataset_type: str,
    source_type: str,
    source_url: str,
    source_file: str,
    source_sha256: str,
    version: str,
    region_code: str,
    row_count: int,
) -> tuple[int, bool]:
    cursor.execute("SELECT id FROM import_batch WHERE batch_key=%s", (batch_key,))
    row = cursor.fetchone()
    if row:
        return int(row[0]), True
    timestamp = now_utc()
    cursor.execute(
        """INSERT INTO import_batch
        (batch_key,dataset_type,source_type,source_url,source_file,source_sha256,region_code,data_version,row_count,
         success_count,failed_count,skipped_count,license_text,status,rollback_status,created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,0,0,0,%s,'PENDING','NOT_REQUESTED',%s)""",
        (batch_key, dataset_type, source_type, source_url, source_file[:500], source_sha256, region_code, version, row_count,
         "Generated/imported by ChargeOps Step 9 workflow.", timestamp),
    )
    return int(cursor.lastrowid), False


def update_batch(cursor, batch_id: int, row_count: int, success: int, failed: int, skipped: int, status: str, failure_file: str | None = None) -> None:
    cursor.execute(
        """UPDATE import_batch SET row_count=%s,success_count=%s,failed_count=%s,skipped_count=%s,status=%s,
        failure_report_file=%s,completed_at=%s WHERE id=%s""",
        (row_count, success, failed, skipped, status, failure_file, now_utc(), batch_id),
    )


def record_error(cursor, batch_id: int, source_file: str, row_number: int | None, field: str, code: str, message: str, raw: dict[str, Any]) -> None:
    cursor.execute(
        """INSERT INTO import_row_error
        (import_batch_id,source_file,source_row_number,field_name,error_code,error_message,raw_payload,created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (batch_id, source_file, row_number, field, code, message, json.dumps(raw, ensure_ascii=False), now_utc()),
    )


def get_station_by_key(cursor, external_key: str, version: str) -> int | None:
    cursor.execute("SELECT id FROM charging_station WHERE external_station_key=%s AND data_version=%s LIMIT 1", (external_key, version))
    row = cursor.fetchone()
    return int(row[0]) if row else None


def import_public(env: dict[str, str], public_file: Path) -> dict[str, Any]:
    rows = read_csv(public_file)
    required = {"external_station_id", "station_name", "operator_name", "latitude", "longitude", "station_status", "access_type", "data_version"}
    missing = required - set(rows[0] if rows else {})
    if missing:
        raise ValueError(f"public cleaned file missing columns: {sorted(missing)}")
    manifest = json.loads(PUBLIC_MANIFEST.read_text(encoding="utf-8"))
    failed_file = PROJECT_ROOT / "data" / "processed" / "afdc_electric_stations_ca_2026-10-29_failed.csv"
    failed_rows = read_csv(failed_file) if failed_file.exists() else []
    raw_manifest = json.loads((PROJECT_ROOT / "data" / "manifests" / "afdc_electric_stations_ca_2026-10-29.json").read_text(encoding="utf-8"))
    source_url = raw_manifest["source_url"]
    version = rows[0]["data_version"] if rows else "2026-10-29"
    connection = connect(env)
    batch_reference = str(manifest["import_batch_id"])
    batch_id: int | None = int(batch_reference) if batch_reference.isdigit() else None
    try:
        with connection.cursor() as cursor:
            if batch_id is None:
                cursor.execute("SELECT id FROM import_batch WHERE batch_key=%s", (batch_reference,))
                found = cursor.fetchone()
                if found:
                    batch_id = int(found[0])
            if batch_id is None:
                raise ValueError(f"manifest import batch reference does not exist: {batch_reference}")
            cursor.execute("SELECT batch_key FROM import_batch WHERE id=%s", (batch_id,))
            existing = cursor.fetchone()
            if not existing:
                raise ValueError(f"manifest import_batch_id={batch_id} does not exist")
            cursor.execute("DELETE FROM import_row_error WHERE import_batch_id=%s AND resolved_at IS NULL", (batch_id,))
            cursor.execute("UPDATE import_batch SET status='PENDING',rollback_status='NOT_REQUESTED',completed_at=NULL WHERE id=%s", (batch_id,))
            region_id = ensure_region(cursor, "CA", "California", "public", source_url, batch_id, version)
            timestamp = now_utc()
            station_count = 0
            connector_count = 0
            errors = 0
            for row_number, row in enumerate(rows, start=2):
                try:
                    external_id = as_int(row["external_station_id"])
                    if external_id <= 0:
                        raise ValueError("external_station_id must be positive")
                    latitude = as_float(row["latitude"])
                    longitude = as_float(row["longitude"])
                    if latitude is None or longitude is None or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                        raise ValueError("coordinates are missing or out of range")
                    operator_id = ensure_operator(cursor, row["operator_name"] or "Non-Networked", "public", source_url, batch_id, version)
                    cursor.execute(
                        """INSERT INTO charging_station
                        (external_station_id,external_station_key,region_id,operator_id,station_name,street_address,city,state,zip_code,country,
                         latitude,longitude,status_code,access_code,access_detail_code,facility_type,ev_network_web,ev_connector_types,
                         total_connector_count,date_last_confirmed,updated_at_source,open_date,funding_sources,source_type,source_url,source_file,
                         data_version,import_batch_id,created_at,updated_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON DUPLICATE KEY UPDATE external_station_key=VALUES(external_station_key),region_id=VALUES(region_id),operator_id=VALUES(operator_id),
                         station_name=VALUES(station_name),street_address=VALUES(street_address),city=VALUES(city),state=VALUES(state),zip_code=VALUES(zip_code),
                         country=VALUES(country),latitude=VALUES(latitude),longitude=VALUES(longitude),status_code=VALUES(status_code),access_code=VALUES(access_code),
                         access_detail_code=VALUES(access_detail_code),facility_type=VALUES(facility_type),ev_connector_types=VALUES(ev_connector_types),
                         total_connector_count=VALUES(total_connector_count),date_last_confirmed=VALUES(date_last_confirmed),updated_at_source=VALUES(updated_at_source),
                         open_date=VALUES(open_date),funding_sources=VALUES(funding_sources),import_batch_id=VALUES(import_batch_id),updated_at=VALUES(updated_at)""",
                        (external_id, str(external_id), region_id, operator_id, row["station_name"], row.get("street_address"), row.get("city"), row.get("state"),
                         row.get("zip_code"), row.get("country"), latitude, longitude, row["station_status"], row["access_type"], None, row.get("facility_type"),
                         None, row.get("charging_connector_types_raw"), as_int(row.get("total_connector_count")), as_date(row.get("date_last_confirmed")),
                         row.get("updated_at_source_utc"), as_date(row.get("open_date")), None, "public", source_url,
                         str(public_file.relative_to(PROJECT_ROOT)), version, batch_id, timestamp, timestamp),
                    )
                    cursor.execute("SELECT id FROM charging_station WHERE external_station_id=%s AND data_version=%s", (external_id, version))
                    station_id = int(cursor.fetchone()[0])
                    for connector_type, value in (("LEVEL1", row.get("level1_count")), ("LEVEL2", row.get("level2_count")), ("DC_FAST", row.get("dc_fast_count")), ("OTHER", row.get("other_connector_count"))):
                        quantity = as_int(value)
                        if quantity <= 0:
                            continue
                        cursor.execute(
                            """INSERT INTO charging_connector(station_id,connector_type,quantity,source_type,source_url,data_version,import_batch_id,created_at,updated_at)
                            VALUES (%s,%s,%s,'public',%s,%s,%s,%s,%s)
                            ON DUPLICATE KEY UPDATE quantity=VALUES(quantity),import_batch_id=VALUES(import_batch_id),updated_at=VALUES(updated_at)""",
                            (station_id, connector_type, quantity, source_url, version, batch_id, timestamp, timestamp),
                        )
                        connector_count += 1
                    station_count += 1
                except Exception as exc:
                    errors += 1
                    record_error(cursor, batch_id, str(public_file.relative_to(PROJECT_ROOT)), row_number, "row", "PUBLIC_ROW_INVALID", str(exc), row)
            status = "PARTIAL" if errors or failed_rows else "IMPORTED"
            update_batch(cursor, batch_id, max(len(rows) + len(failed_rows), int(raw_manifest.get("row_count", len(rows)))), station_count, errors + len(failed_rows), 0, status, str(failed_file.relative_to(PROJECT_ROOT)) if failed_file.exists() else None)
        connection.commit()
        return {"batch_id": batch_id, "status": status, "station_rows": station_count, "connector_rows": connector_count, "failed_rows": errors + len(failed_rows)}
    except Exception:
        connection.rollback()
        with connect(env, autocommit=True).cursor() as cursor:
            cursor.execute("UPDATE import_batch SET status='FAILED',completed_at=%s WHERE id=%s", (now_utc(), batch_id))
        raise
    finally:
        connection.close()


SYNTHETIC_STATIONS = {
    f"SYN-ST-{index:03d}": (900000000 + index, city, latitude, longitude)
    for index, (city, latitude, longitude) in enumerate(
        [("Los Angeles", 34.0522, -118.2437), ("San Diego", 32.7157, -117.1611), ("San Jose", 37.3382, -121.8863),
         ("Sacramento", 38.5816, -121.4944), ("Fresno", 36.7378, -119.7871), ("Irvine", 33.6846, -117.8265),
         ("Oakland", 37.8044, -122.2712), ("Riverside", 33.9806, -117.3755), ("Bakersfield", 35.3733, -119.0187),
         ("Stockton", 37.9577, -121.2908), ("Modesto", 37.6391, -120.9969), ("Santa Rosa", 38.4404, -122.7141)], start=1
    )
}


def import_synthetic(env: dict[str, str], synthetic_dir: Path) -> dict[str, Any]:
    manifest = json.loads(SYNTHETIC_MANIFEST.read_text(encoding="utf-8"))
    files = {Path(item["path"]).name: synthetic_dir / Path(item["path"]).name for item in manifest["files"]}
    rows_by_file = {name: read_csv(path) for name, path in files.items()}
    total_rows = sum(len(rows) for rows in rows_by_file.values())
    source_hash = sha256_file(SYNTHETIC_MANIFEST)
    source_files = ";".join(sorted(str(path.relative_to(PROJECT_ROOT)) for path in files.values()))
    batch_key = manifest["synthetic_batch_id"]
    connection = connect(env)
    try:
        with connection.cursor() as cursor:
            batch_id, _ = ensure_batch(cursor, batch_key, "synthetic_demo", "synthetic", "synthetic://chargeops/demo", source_files, source_hash, SYNTHETIC_VERSION, "CA", total_rows)
        connection.commit()
        with connection.cursor() as cursor:
            region_id = ensure_region(cursor, "CA", "California", "synthetic", "synthetic://chargeops/demo", batch_id, SYNTHETIC_VERSION)
            cursor.execute("DELETE FROM import_row_error WHERE import_batch_id=%s AND resolved_at IS NULL", (batch_id,))
            cursor.execute("UPDATE import_batch SET status='PENDING',rollback_status='NOT_REQUESTED',completed_at=NULL WHERE id=%s", (batch_id,))
            cursor.execute("DELETE FROM policy_condition WHERE import_batch_id=%s AND condition_key='eligibility'", (batch_id,))
            operator_id = ensure_operator(cursor, "Synthetic Operator", "synthetic", "synthetic://chargeops/demo", batch_id, SYNTHETIC_VERSION)
            timestamp = now_utc()
            station_ids: dict[str, int] = {}
            for external_key, (external_id, city, latitude, longitude) in SYNTHETIC_STATIONS.items():
                cursor.execute(
                    """INSERT INTO charging_station
                    (external_station_id,external_station_key,region_id,operator_id,station_name,city,state,country,latitude,longitude,status_code,access_code,
                     facility_type,total_connector_count,source_type,source_url,source_file,data_version,import_batch_id,created_at,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,'CA','US',%s,%s,'OPEN','PUBLIC','SYNTHETIC',0,'synthetic','synthetic://chargeops/demo',%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE region_id=VALUES(region_id),operator_id=VALUES(operator_id),station_name=VALUES(station_name),
                     city=VALUES(city),latitude=VALUES(latitude),longitude=VALUES(longitude),import_batch_id=VALUES(import_batch_id),updated_at=VALUES(updated_at)""",
                    (external_id, external_key, region_id, operator_id, f"{external_key} Synthetic Station", city, latitude, longitude,
                     str(files["station_metrics_synthetic_2026-10-29.csv"].relative_to(PROJECT_ROOT)), SYNTHETIC_VERSION, batch_id, timestamp, timestamp),
                )
                cursor.execute("SELECT id FROM charging_station WHERE external_station_key=%s AND data_version=%s", (external_key, SYNTHETIC_VERSION))
                station_ids[external_key] = int(cursor.fetchone()[0])

            failures = 0
            successes = 0
            for name, rows in rows_by_file.items():
                path = files[name]
                for row_number, row in enumerate(rows, start=2):
                    try:
                        for key in ("source_type", "generator_version", "generated_at", "synthetic_batch_id"):
                            if not row.get(key):
                                raise ValueError(f"missing {key}")
                        if row["source_type"] != "synthetic" or row["synthetic_batch_id"] != batch_key:
                            raise ValueError("synthetic metadata does not match batch")
                        if name.startswith("candidate_sites_"):
                            cursor.execute(
                                """INSERT INTO candidate_site
                                (external_candidate_id,region_id,site_name,city,state,latitude,longitude,area_sqm,parking_spaces,electric_capacity_kw,budget_usd,
                                 traffic_index,population_density,planned_open_date,data_as_of,data_status,lifecycle_status,source_type,source_url,source_file,data_version,import_batch_id,created_at,updated_at)
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'DRAFT','synthetic','synthetic://chargeops/demo',%s,%s,%s,%s,%s)
                                ON DUPLICATE KEY UPDATE region_id=VALUES(region_id),site_name=VALUES(site_name),latitude=VALUES(latitude),longitude=VALUES(longitude),
                                 area_sqm=VALUES(area_sqm),parking_spaces=VALUES(parking_spaces),electric_capacity_kw=VALUES(electric_capacity_kw),budget_usd=VALUES(budget_usd),
                                 traffic_index=VALUES(traffic_index),population_density=VALUES(population_density),planned_open_date=VALUES(planned_open_date),data_as_of=VALUES(data_as_of),
                                 data_status=VALUES(data_status),import_batch_id=VALUES(import_batch_id),updated_at=VALUES(updated_at)""",
                                (row["candidate_site_external_id"], region_id, row["site_name"], row.get("city"), row.get("state"), as_float(row.get("latitude")), as_float(row.get("longitude")),
                                 as_float(row.get("area_sqm")), as_int(row.get("parking_spaces")), as_float(row.get("electric_capacity_kw")), as_float(row.get("budget_usd")),
                                 as_float(row.get("traffic_index")), as_float(row.get("population_density")), as_date(row.get("planned_open_date")), as_date(row.get("data_as_of")), row["data_status"],
                                 str(path.relative_to(PROJECT_ROOT)), SYNTHETIC_VERSION, batch_id, timestamp, timestamp),
                            )
                        elif name.startswith("station_metrics_"):
                            station_id = station_ids[row["station_external_id"]]
                            cursor.execute(
                                """INSERT INTO station_operation_metric
                                (station_id,metric_date,metric_hour,timezone,charging_sessions,energy_kwh,peak_power_kw,occupancy_rate,avg_session_minutes,data_as_of,source_type,source_url,source_file,data_version,import_batch_id,created_at,updated_at)
                                VALUES (%s,%s,%s,'America/Los_Angeles',%s,%s,%s,%s,%s,%s,'synthetic','synthetic://chargeops/demo',%s,%s,%s,%s,%s)
                                ON DUPLICATE KEY UPDATE charging_sessions=VALUES(charging_sessions),energy_kwh=VALUES(energy_kwh),peak_power_kw=VALUES(peak_power_kw),occupancy_rate=VALUES(occupancy_rate),
                                 avg_session_minutes=VALUES(avg_session_minutes),data_as_of=VALUES(data_as_of),import_batch_id=VALUES(import_batch_id),updated_at=VALUES(updated_at)""",
                                (station_id, as_date(row["metric_date"]), as_int(row["metric_hour"]), as_int(row["charging_sessions"]), as_float(row["energy_kwh"]),
                                 as_float(row["peak_power_kw"]), as_float(row["occupancy_rate"]), as_float(row["avg_session_minutes"]), as_date(row["data_as_of"]),
                                 str(path.relative_to(PROJECT_ROOT)), SYNTHETIC_VERSION, batch_id, timestamp, timestamp),
                            )
                        elif name.startswith("station_faults_"):
                            station_id = station_ids[row["station_external_id"]]
                            cursor.execute(
                                """INSERT INTO station_fault_event
                                (station_id,external_fault_id,fault_type,severity,started_at,recovered_at,affected_connectors,root_cause,status,data_as_of,source_type,source_url,source_file,data_version,import_batch_id,created_at,updated_at)
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'synthetic','synthetic://chargeops/demo',%s,%s,%s,%s,%s)
                                ON DUPLICATE KEY UPDATE fault_type=VALUES(fault_type),severity=VALUES(severity),started_at=VALUES(started_at),recovered_at=VALUES(recovered_at),
                                 affected_connectors=VALUES(affected_connectors),root_cause=VALUES(root_cause),data_as_of=VALUES(data_as_of),import_batch_id=VALUES(import_batch_id),updated_at=VALUES(updated_at)""",
                                (station_id, row["fault_id"], row["fault_type"], row["severity"], as_mysql_datetime(row["started_at"]), as_mysql_datetime(row["recovered_at"]),
                                 as_int(row["affected_connectors"]), row.get("root_cause"), "RECOVERED" if row.get("recovered_at") else "OPEN", as_date(row["data_as_of"]),
                                 str(path.relative_to(PROJECT_ROOT)), SYNTHETIC_VERSION, batch_id, timestamp, timestamp),
                            )
                        elif name.startswith("expansion_cases_"):
                            station_id = station_ids[row["station_external_id"]]
                            cursor.execute(
                                """INSERT INTO expansion_plan
                                (external_case_id,station_id,existing_fast_connectors,existing_slow_connectors,peak_occupancy_rate,fault_count_30d,available_capacity_kw,
                                 proposed_fast_connectors,proposed_slow_connectors,requested_budget_usd,priority,preconditions,confirmation_status,source_type,source_url,source_file,data_version,import_batch_id,created_at,updated_at)
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'WAITING_CONFIRMATION','synthetic','synthetic://chargeops/demo',%s,%s,%s,%s,%s)
                                ON DUPLICATE KEY UPDATE station_id=VALUES(station_id),peak_occupancy_rate=VALUES(peak_occupancy_rate),fault_count_30d=VALUES(fault_count_30d),available_capacity_kw=VALUES(available_capacity_kw),
                                 proposed_fast_connectors=VALUES(proposed_fast_connectors),proposed_slow_connectors=VALUES(proposed_slow_connectors),requested_budget_usd=VALUES(requested_budget_usd),
                                 priority=VALUES(priority),preconditions=VALUES(preconditions),import_batch_id=VALUES(import_batch_id),updated_at=VALUES(updated_at)""",
                                (row["case_external_id"], station_id, as_int(row["existing_fast_connectors"]), as_int(row["existing_slow_connectors"]), as_float(row["peak_occupancy_rate"]),
                                 as_int(row["fault_count_30d"]), as_float(row.get("available_capacity_kw")), as_int(row["proposed_fast_connectors"]), as_int(row["proposed_slow_connectors"]),
                                 as_float(row["requested_budget_usd"]), row["priority"], json.dumps([row.get("preconditions", "")], ensure_ascii=False), str(path.relative_to(PROJECT_ROOT)), SYNTHETIC_VERSION, batch_id, timestamp, timestamp),
                            )
                        elif name.startswith("policy_matching_"):
                            cursor.execute(
                                """INSERT INTO policy_condition
                                (policy_code,policy_version,title,policy_type,region_id,applicant_type,condition_key,condition_operator,condition_value,required_materials,
                                 effective_from,application_deadline,source_type,source_url,source_file,data_version,import_batch_id,created_at,updated_at)
                                VALUES (%s,%s,%s,'SUBSIDY',%s,%s,%s,'EQUALS',%s,%s,%s,%s,'synthetic','synthetic://chargeops/demo',%s,%s,%s,%s,%s)
                                ON DUPLICATE KEY UPDATE title=VALUES(title),condition_value=VALUES(condition_value),required_materials=VALUES(required_materials),application_deadline=VALUES(application_deadline),
                                 import_batch_id=VALUES(import_batch_id),updated_at=VALUES(updated_at)""",
                                (row["policy_code"], row["policy_version"], f"Synthetic {row['policy_code']} eligibility", region_id, row["applicant_type"], f"eligibility:{row['candidate_site_external_id']}",
                                 json.dumps({"eligible_flag": row["eligible_flag"], "candidate_site_external_id": row["candidate_site_external_id"]}, ensure_ascii=False),
                                 json.dumps([x for x in row.get("missing_materials", "").split(";") if x], ensure_ascii=False), as_date(row["data_as_of"]), as_date(row["application_deadline"]),
                                 str(path.relative_to(PROJECT_ROOT)), SYNTHETIC_VERSION, batch_id, timestamp, timestamp),
                            )
                        successes += 1
                    except Exception as exc:
                        failures += 1
                        record_error(cursor, batch_id, str(path.relative_to(PROJECT_ROOT)), row_number, "row", "SYNTHETIC_ROW_INVALID", str(exc), row)
            status = "PARTIAL" if failures else "IMPORTED"
            update_batch(cursor, batch_id, total_rows, successes, failures, 0, status)
        connection.commit()
        return {"batch_id": batch_id, "status": status, "rows": total_rows, "success": successes, "failed": failures, "synthetic_stations": len(station_ids)}
    except Exception:
        connection.rollback()
        with connect(env, autocommit=True).cursor() as cursor:
            cursor.execute("UPDATE import_batch SET status='FAILED',completed_at=%s WHERE id=%s", (now_utc(), batch_id))
        raise
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", choices=("public", "synthetic", "all"), default="all")
    parser.add_argument("--public-file", type=Path, default=PUBLIC_DEFAULT)
    parser.add_argument("--synthetic-dir", type=Path, default=SYNTHETIC_DIR)
    args = parser.parse_args()
    env = load_env()
    results: dict[str, Any] = {}
    if args.dataset in ("public", "all"):
        results["public"] = import_public(env, args.public_file)
    if args.dataset in ("synthetic", "all"):
        results["synthetic"] = import_synthetic(env, args.synthetic_dir)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
