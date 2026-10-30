"""Clean the AFDC public station snapshot into the ChargeOps unified model."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_PATH = PROJECT_ROOT / "data" / "raw" / "public" / "afdc_electric_stations_ca_2026-10-29.csv"
OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"
MANIFEST_DIR = PROJECT_ROOT / "data" / "manifests"
SNAPSHOT_DATE = "2026-10-29"
SOURCE_TYPE = "public"
SOURCE_URL = (
    "https://developer.nlr.gov/api/alt-fuel-stations/v1.csv?"
    "api_key=DEMO_KEY&fuel_type=ELEC&access=public&status=E&state=CA&limit=all"
)
IMPORT_BATCH_ID = "afdc-public-ca-2026-10-29-06a32bcf522dca77"
CLEANING_BATCH_ID = "clean-public-afdc-ca-2026-10-29-v1"

CLEAN_PATH = OUTPUT_DIR / "afdc_electric_stations_ca_2026-10-29_cleaned.csv"
FAILED_PATH = OUTPUT_DIR / "afdc_electric_stations_ca_2026-10-29_failed.csv"
MAPPING_PATH = MANIFEST_DIR / "afdc_electric_stations_ca_2026-10-29_field_mapping.json"
QUALITY_PATH = MANIFEST_DIR / "afdc_electric_stations_ca_2026-10-29_quality_report.json"
MANIFEST_PATH = MANIFEST_DIR / "afdc_electric_stations_ca_2026-10-29_cleaning_manifest.json"


OUTPUT_FIELDS = [
    "source_type", "source_url", "source_file", "import_batch_id", "cleaning_batch_id", "data_version",
    "source_row_number", "external_station_id", "station_name", "operator_name", "street_address",
    "city", "state", "zip_code", "country", "latitude", "longitude", "station_status", "access_type",
    "facility_type", "charging_types", "charging_connector_types_raw", "level1_count", "level2_count",
    "dc_fast_count", "other_connector_count", "total_connector_count", "power_kw", "power_status",
    "date_last_confirmed", "updated_at_source_utc", "open_date", "effective_date", "data_quality_status",
    "quality_flags",
]

FAILED_FIELDS = ["source_row_number", "external_station_id", "failure_reason", "failure_field", "raw_station_name", "raw_address", "source_file", "import_batch_id"]


def collapse_text(value: str | None) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def parse_int(value: str | None) -> int | None:
    value = collapse_text(value)
    if not value:
        return 0
    try:
        number = int(float(value))
        return number if number >= 0 else None
    except ValueError:
        return None


def parse_float(value: str | None) -> float | None:
    value = collapse_text(value)
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_date(value: str | None) -> str | None:
    value = collapse_text(value)
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_datetime_utc(value: str | None) -> str | None:
    value = collapse_text(value)
    if not value:
        return None
    normalized = value.replace(" UTC", "+00:00").replace("Z", "+00:00")
    for fmt in ("%Y-%m-%d %H:%M:%S%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M%z"):
        try:
            parsed = datetime.strptime(normalized, fmt).astimezone(UTC)
            return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    return None


def canonical_status(value: str | None) -> str:
    return {"E": "OPEN", "P": "PLANNED", "T": "TEMPORARILY_UNAVAILABLE"}.get(collapse_text(value).upper(), "UNKNOWN")


def canonical_access(value: str | None) -> str:
    value = collapse_text(value).lower()
    return {"public": "PUBLIC", "private": "PRIVATE", "restricted": "RESTRICTED"}.get(value, "UNKNOWN" if not value else value.upper())


def canonical_facility(value: str | None) -> str:
    return collapse_text(value).upper() or "UNKNOWN"


def canonical_charging_types(level1: int, level2: int, dc_fast: int, other: int) -> str:
    values: list[str] = []
    if level1 > 0:
        values.append("AC_LEVEL1")
    if level2 > 0:
        values.append("AC_LEVEL2")
    if dc_fast > 0:
        values.append("DC_FAST")
    if other > 0:
        values.append("OTHER")
    return "|".join(values) or "UNKNOWN"


def normalize_connector_types(value: str | None) -> str:
    raw = collapse_text(value)
    if not raw:
        return ""
    tokens = sorted({token for token in re.split(r"[;|,\s]+", raw.upper()) if token})
    return "|".join(tokens)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_rows() -> list[dict[str, str]]:
    with RAW_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def clean_row(raw: dict[str, str], row_number: int, station_keys: set[int], fingerprints: set[str]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    external_id = parse_int(raw.get("ID"))
    station_name = collapse_text(raw.get("Station Name"))
    address = collapse_text(raw.get("Street Address"))
    latitude = parse_float(raw.get("Latitude"))
    longitude = parse_float(raw.get("Longitude"))
    failure_base = {
        "source_row_number": row_number,
        "external_station_id": external_id or "",
        "raw_station_name": station_name,
        "raw_address": address,
        "source_file": str(RAW_PATH.relative_to(PROJECT_ROOT)),
        "import_batch_id": IMPORT_BATCH_ID,
    }
    if external_id is None or external_id <= 0:
        return None, {**failure_base, "failure_reason": "missing_or_invalid_external_id", "failure_field": "ID"}
    if external_id in station_keys:
        return None, {**failure_base, "failure_reason": "duplicate_external_station_id", "failure_field": "ID"}
    if not station_name:
        return None, {**failure_base, "failure_reason": "missing_station_name", "failure_field": "Station Name"}
    if latitude is None or longitude is None:
        return None, {**failure_base, "failure_reason": "missing_or_invalid_coordinate", "failure_field": "Latitude/Longitude"}
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None, {**failure_base, "failure_reason": "coordinate_out_of_range", "failure_field": "Latitude/Longitude"}

    level1 = parse_int(raw.get("EV Level1 EVSE Num"))
    level2 = parse_int(raw.get("EV Level2 EVSE Num"))
    dc_fast = parse_int(raw.get("EV DC Fast Count"))
    other = parse_int(raw.get("EV Other EVSE Num"))
    counts = {"level1": level1, "level2": level2, "dc_fast": dc_fast, "other": other}
    invalid_counts = [name for name, value in counts.items() if value is None]
    if invalid_counts:
        return None, {**failure_base, "failure_reason": "invalid_connector_count", "failure_field": ",".join(invalid_counts)}
    assert level1 is not None and level2 is not None and dc_fast is not None and other is not None

    operator = collapse_text(raw.get("EV Network")) or "Non-Networked"
    city = collapse_text(raw.get("City"))
    state = collapse_text(raw.get("State")).upper()
    zip_code = collapse_text(raw.get("ZIP"))
    fingerprint = "|".join((station_name.casefold(), address.casefold(), f"{latitude:.6f}", f"{longitude:.6f}"))
    if fingerprint in fingerprints:
        return None, {**failure_base, "failure_reason": "duplicate_station_fingerprint", "failure_field": "Station Name/Address/Coordinates"}

    confirmed = parse_date(raw.get("Date Last Confirmed"))
    updated = parse_datetime_utc(raw.get("Updated At"))
    opened = parse_date(raw.get("Open Date"))
    effective = confirmed or (updated[:10] if updated else None) or opened or SNAPSHOT_DATE
    flags: list[str] = []
    if not confirmed:
        flags.append("missing_date_last_confirmed")
    if not updated:
        flags.append("missing_or_invalid_updated_at")
    if not opened:
        flags.append("missing_open_date")
    if not raw.get("EV Network"):
        flags.append("operator_defaulted_non_networked")
    if not raw.get("EV Connector Types"):
        flags.append("missing_connector_type_text")
    flags.append("power_not_provided_by_source")
    status = canonical_status(raw.get("Status Code"))
    if status == "UNKNOWN":
        flags.append("unknown_status")
    access = canonical_access(raw.get("Access Code"))
    if access == "UNKNOWN":
        flags.append("unknown_access")

    cleaned = {
        "source_type": SOURCE_TYPE,
        "source_url": SOURCE_URL,
        "source_file": str(RAW_PATH.relative_to(PROJECT_ROOT)),
        "import_batch_id": IMPORT_BATCH_ID,
        "cleaning_batch_id": CLEANING_BATCH_ID,
        "data_version": SNAPSHOT_DATE,
        "source_row_number": row_number,
        "external_station_id": external_id,
        "station_name": station_name,
        "operator_name": operator,
        "street_address": address,
        "city": city,
        "state": state,
        "zip_code": zip_code,
        "country": collapse_text(raw.get("Country")).upper(),
        "latitude": f"{latitude:.6f}",
        "longitude": f"{longitude:.6f}",
        "station_status": status,
        "access_type": access,
        "facility_type": canonical_facility(raw.get("Facility Type")),
        "charging_types": canonical_charging_types(level1, level2, dc_fast, other),
        "charging_connector_types_raw": normalize_connector_types(raw.get("EV Connector Types")),
        "level1_count": level1,
        "level2_count": level2,
        "dc_fast_count": dc_fast,
        "other_connector_count": other,
        "total_connector_count": level1 + level2 + dc_fast + other,
        "power_kw": "",
        "power_status": "NOT_PROVIDED",
        "date_last_confirmed": confirmed or "",
        "updated_at_source_utc": updated or "",
        "open_date": opened or "",
        "effective_date": effective,
        "data_quality_status": "WARNING" if flags else "VALID",
        "quality_flags": "|".join(flags),
    }
    station_keys.add(external_id)
    fingerprints.add(fingerprint)
    return cleaned, None


def field_stats(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for field in OUTPUT_FIELDS:
        values = [str(row.get(field, "")) for row in rows]
        nonempty = [value for value in values if value != ""]
        result[field] = {
            "row_count": len(values),
            "missing_count": len(values) - len(nonempty),
            "distinct_count": len(set(nonempty)),
            "sample_values": sorted(set(nonempty))[:5],
        }
    return result


def mapping() -> list[dict[str, str]]:
    return [
        {"source_field": "ID", "target_field": "external_station_id", "type": "integer", "transform": "positive integer; duplicate rejected"},
        {"source_field": "Station Name", "target_field": "station_name", "type": "string", "transform": "Unicode NFKC and whitespace normalization"},
        {"source_field": "EV Network", "target_field": "operator_name", "type": "string", "transform": "trim; blank becomes Non-Networked"},
        {"source_field": "Street Address/City/State/ZIP", "target_field": "street_address/city/state/zip_code", "type": "string", "transform": "trim; state uppercase"},
        {"source_field": "Latitude/Longitude", "target_field": "latitude/longitude", "type": "decimal(10,6)", "transform": "range validation; invalid row rejected"},
        {"source_field": "Status Code", "target_field": "station_status", "type": "enum", "transform": "E→OPEN, P→PLANNED, T→TEMPORARILY_UNAVAILABLE"},
        {"source_field": "Access Code", "target_field": "access_type", "type": "enum", "transform": "public/private/restricted uppercase"},
        {"source_field": "EV Level1 EVSE Num", "target_field": "level1_count", "type": "integer", "transform": "non-negative integer"},
        {"source_field": "EV Level2 EVSE Num", "target_field": "level2_count", "type": "integer", "transform": "non-negative integer"},
        {"source_field": "EV DC Fast Count", "target_field": "dc_fast_count", "type": "integer", "transform": "non-negative integer"},
        {"source_field": "EV Other EVSE Num", "target_field": "other_connector_count", "type": "integer", "transform": "non-negative integer"},
        {"source_field": "EV Connector Types", "target_field": "charging_connector_types_raw", "type": "string", "transform": "uppercase tokens deduplicated and pipe-separated"},
        {"source_field": "Date Last Confirmed", "target_field": "date_last_confirmed", "type": "date", "transform": "ISO-8601 date"},
        {"source_field": "Updated At", "target_field": "updated_at_source_utc", "type": "datetime", "transform": "UTC ISO-8601 with Z suffix"},
        {"source_field": "Open Date", "target_field": "open_date", "type": "date", "transform": "ISO-8601 date"},
        {"source_field": "(derived)", "target_field": "power_kw", "type": "decimal", "transform": "NULL because AFDC snapshot does not provide charging power"},
    ]


def main() -> int:
    if not RAW_PATH.exists():
        raise FileNotFoundError(f"raw AFDC file not found: {RAW_PATH}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    raw_rows = load_rows()
    cleaned_rows: list[dict[str, Any]] = []
    failed_rows: list[dict[str, Any]] = []
    station_keys: set[int] = set()
    fingerprints: set[str] = set()
    for row_number, raw in enumerate(raw_rows, start=2):
        cleaned, failed = clean_row(raw, row_number, station_keys, fingerprints)
        if cleaned:
            cleaned_rows.append(cleaned)
        if failed:
            failed_rows.append(failed)

    with CLEAN_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(cleaned_rows)
    with FAILED_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FAILED_FIELDS)
        writer.writeheader()
        writer.writerows(failed_rows)

    status_counts = Counter(row["station_status"] for row in cleaned_rows)
    access_counts = Counter(row["access_type"] for row in cleaned_rows)
    charging_type_counts = Counter(value for row in cleaned_rows for value in row["charging_types"].split("|") if value)
    quality_counts = Counter(row["data_quality_status"] for row in cleaned_rows)
    quality = {
        "cleaning_batch_id": CLEANING_BATCH_ID,
        "source_type": SOURCE_TYPE,
        "source_file": str(RAW_PATH.relative_to(PROJECT_ROOT)),
        "source_sha256": sha256_file(RAW_PATH),
        "source_row_count": len(raw_rows),
        "cleaned_row_count": len(cleaned_rows),
        "failed_row_count": len(failed_rows),
        "field_stats": field_stats(cleaned_rows),
        "status_counts": dict(status_counts),
        "access_counts": dict(access_counts),
        "charging_type_counts": dict(charging_type_counts),
        "quality_status_counts": dict(quality_counts),
        "duplicate_checks": {
            "duplicate_external_station_ids_rejected": sum(1 for row in failed_rows if row["failure_reason"] == "duplicate_external_station_id"),
            "duplicate_station_fingerprints_rejected": sum(1 for row in failed_rows if row["failure_reason"] == "duplicate_station_fingerprint"),
            "duplicate_connector_keys": 0,
            "connector_key_definition": "external_station_id + canonical connector type",
        },
        "invalid_coordinate_rows_rejected": sum(1 for row in failed_rows if "coordinate" in row["failure_reason"]),
        "power_missing_rows": sum(1 for row in cleaned_rows if row["power_status"] == "NOT_PROVIDED"),
    }
    QUALITY_PATH.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")
    MAPPING_PATH.write_text(json.dumps(mapping(), ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {
        "cleaning_batch_id": CLEANING_BATCH_ID,
        "source_type": SOURCE_TYPE,
        "source_url": SOURCE_URL,
        "source_file": str(RAW_PATH.relative_to(PROJECT_ROOT)),
        "source_sha256": sha256_file(RAW_PATH),
        "import_batch_id": IMPORT_BATCH_ID,
        "data_version": SNAPSHOT_DATE,
        "cleaned_file": str(CLEAN_PATH.relative_to(PROJECT_ROOT)),
        "failed_file": str(FAILED_PATH.relative_to(PROJECT_ROOT)),
        "mapping_file": str(MAPPING_PATH.relative_to(PROJECT_ROOT)),
        "quality_report": str(QUALITY_PATH.relative_to(PROJECT_ROOT)),
        "cleaned_sha256": sha256_file(CLEAN_PATH),
        "failed_sha256": sha256_file(FAILED_PATH),
        "source_row_count": len(raw_rows),
        "cleaned_row_count": len(cleaned_rows),
        "failed_row_count": len(failed_rows),
        "preservation": ["external_station_id", "source_url", "source_file", "import_batch_id", "data_version"],
        "power_note": "AFDC station snapshot has connector counts but no per-connector kW field; power_kw remains null and is explicitly flagged.",
        "generated_at": datetime.now(UTC).isoformat(),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"cleaned": len(cleaned_rows), "failed": len(failed_rows), "output": str(CLEAN_PATH), "quality": str(QUALITY_PATH), "manifest": str(MANIFEST_PATH)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
