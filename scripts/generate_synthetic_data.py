"""Create deterministic ChargeOps upload templates and synthetic demo data."""

from __future__ import annotations

import csv
import hashlib
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = PROJECT_ROOT / "data" / "templates"
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "synthetic"
MANIFEST_DIR = PROJECT_ROOT / "data" / "manifests"

SEED = 20261029
GENERATOR_VERSION = "chargeops-synthetic-v1.0.0"
GENERATED_AT = "2026-10-29T12:00:00-07:00"
BATCH_ID = "synthetic-demo-2026-10-29-v1"
CURRENT_DATE = date(2026, 10, 29)

COMMON_FIELDS = ["source_type", "generator_version", "generated_at", "synthetic_batch_id", "scenario"]

TEMPLATES: dict[str, list[str]] = {
    "candidate_sites_template.csv": [
        "candidate_site_external_id", "site_name", "region_code", "city", "state", "latitude",
        "longitude", "area_sqm", "parking_spaces", "electric_capacity_kw", "budget_usd",
        "traffic_index", "population_density", "planned_open_date", "data_as_of", "data_status",
        *COMMON_FIELDS,
    ],
    "station_metrics_template.csv": [
        "station_external_id", "metric_date", "metric_hour", "charging_sessions", "energy_kwh",
        "peak_power_kw", "occupancy_rate", "avg_session_minutes", "data_as_of", "data_status",
        *COMMON_FIELDS,
    ],
    "station_faults_template.csv": [
        "station_external_id", "fault_id", "fault_type", "severity", "started_at", "recovered_at",
        "affected_connectors", "root_cause", "data_as_of", "data_status", *COMMON_FIELDS,
    ],
    "expansion_cases_template.csv": [
        "case_external_id", "station_external_id", "case_date", "existing_fast_connectors",
        "existing_slow_connectors", "peak_occupancy_rate", "fault_count_30d", "available_capacity_kw",
        "requested_budget_usd", "proposed_fast_connectors", "proposed_slow_connectors", "priority",
        "preconditions", "data_as_of", "data_status", *COMMON_FIELDS,
    ],
    "policy_matching_cases_template.csv": [
        "policy_case_id", "candidate_site_external_id", "region_code", "policy_code", "policy_version",
        "applicant_type", "planned_fast_connectors", "planned_slow_connectors", "project_budget_usd",
        "eligible_flag", "missing_materials", "application_deadline", "data_as_of", "data_status",
        *COMMON_FIELDS,
    ],
}


def csv_write(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_templates() -> None:
    for filename, fields in TEMPLATES.items():
        csv_write(TEMPLATE_DIR / filename, fields, [])


def metadata(scenario: str, data_as_of: str, data_status: str = "current") -> dict[str, str]:
    return {
        "data_as_of": data_as_of,
        "data_status": data_status,
        "source_type": "synthetic",
        "generator_version": GENERATOR_VERSION,
        "generated_at": GENERATED_AT,
        "synthetic_batch_id": BATCH_ID,
        "scenario": scenario,
    }


def generate_candidates(rng: random.Random) -> list[dict[str, Any]]:
    cities = [
        ("Los Angeles", 34.0522, -118.2437),
        ("San Diego", 32.7157, -117.1611),
        ("San Jose", 37.3382, -121.8863),
        ("Sacramento", 38.5816, -121.4944),
        ("Fresno", 36.7378, -119.7871),
        ("Irvine", 33.6846, -117.8265),
        ("Oakland", 37.8044, -122.2712),
        ("Riverside", 33.9806, -117.3755),
        ("Bakersfield", 35.3733, -119.0187),
        ("Stockton", 37.9577, -121.2908),
        ("Modesto", 37.6391, -120.9969),
        ("Santa Rosa", 38.4404, -122.7141),
    ]
    scenarios = [
        "normal", "normal", "high_traffic", "low_traffic", "missing_coordinate", "expired_data",
        "high_budget", "normal", "policy_candidate", "normal", "low_traffic", "high_traffic",
    ]
    rows: list[dict[str, Any]] = []
    for index, ((city, latitude, longitude), scenario) in enumerate(zip(cities, scenarios), start=1):
        if scenario == "high_traffic":
            traffic = rng.uniform(0.86, 0.99)
            population = rng.randint(4800, 9200)
        elif scenario == "low_traffic":
            traffic = rng.uniform(0.18, 0.38)
            population = rng.randint(500, 1800)
        else:
            traffic = rng.uniform(0.42, 0.82)
            population = rng.randint(1800, 6200)
        if scenario == "missing_coordinate":
            latitude_value, longitude_value = "", ""
            data_status = "missing_coordinate"
        else:
            latitude_value = f"{latitude + rng.uniform(-0.035, 0.035):.6f}"
            longitude_value = f"{longitude + rng.uniform(-0.035, 0.035):.6f}"
            data_status = "expired" if scenario == "expired_data" else "current"
        data_as_of = "2025-06-30" if scenario == "expired_data" else "2026-10-15"
        rows.append(
            {
                "candidate_site_external_id": f"SYN-CAND-{index:03d}",
                "site_name": f"{city} Synthetic Mobility Hub {index:02d}",
                "region_code": "CA",
                "city": city,
                "state": "CA",
                "latitude": latitude_value,
                "longitude": longitude_value,
                "area_sqm": rng.randint(800, 8500),
                "parking_spaces": rng.randint(25, 420),
                "electric_capacity_kw": "" if scenario == "missing_coordinate" else rng.randint(180, 1800),
                "budget_usd": 95000 if scenario != "high_budget" else 480000,
                "traffic_index": f"{traffic:.3f}",
                "population_density": population,
                "planned_open_date": "2027-06-30" if scenario != "expired_data" else "2026-01-31",
                **metadata(scenario, data_as_of, data_status),
            }
        )
    return rows


def generate_metrics(rng: random.Random) -> list[dict[str, Any]]:
    station_scenarios = {
        "SYN-ST-001": "normal", "SYN-ST-002": "high_utilization", "SYN-ST-003": "high_utilization",
        "SYN-ST-004": "low_utilization", "SYN-ST-005": "normal", "SYN-ST-006": "fault_concentration",
        "SYN-ST-007": "fault_concentration", "SYN-ST-008": "low_utilization", "SYN-ST-009": "expired_data",
        "SYN-ST-010": "normal", "SYN-ST-011": "high_utilization", "SYN-ST-012": "normal",
    }
    rows: list[dict[str, Any]] = []
    for station_id, scenario in station_scenarios.items():
        start = date(2025, 6, 1) if scenario == "expired_data" else date(2026, 10, 1)
        for day_offset in range(14):
            metric_date = start + timedelta(days=day_offset)
            for hour in (8, 12, 18):
                if scenario == "high_utilization":
                    occupancy = rng.uniform(0.84, 0.98)
                    sessions = rng.randint(42, 86)
                elif scenario == "low_utilization":
                    occupancy = rng.uniform(0.08, 0.28)
                    sessions = rng.randint(2, 18)
                elif scenario == "fault_concentration":
                    occupancy = rng.uniform(0.42, 0.72)
                    sessions = rng.randint(16, 46)
                else:
                    occupancy = rng.uniform(0.32, 0.78)
                    sessions = rng.randint(12, 52)
                energy = sessions * rng.uniform(18.0, 42.0)
                rows.append(
                    {
                        "station_external_id": station_id,
                        "metric_date": metric_date.isoformat(),
                        "metric_hour": hour,
                        "charging_sessions": sessions,
                        "energy_kwh": f"{energy:.2f}",
                        "peak_power_kw": f"{energy / rng.uniform(1.4, 2.8):.2f}",
                        "occupancy_rate": f"{occupancy:.3f}",
                        "avg_session_minutes": rng.randint(24, 86),
                        **metadata(scenario, metric_date.isoformat(), "expired" if scenario == "expired_data" else "current"),
                    }
                )
    return rows


def generate_faults(rng: random.Random) -> list[dict[str, Any]]:
    fault_types = ["connector_offline", "payment_error", "communication_loss", "thermal_alarm"]
    rows: list[dict[str, Any]] = []
    event_number = 1
    for station_id in ["SYN-ST-001", "SYN-ST-002", "SYN-ST-003", "SYN-ST-004", "SYN-ST-005", "SYN-ST-008", "SYN-ST-010", "SYN-ST-011", "SYN-ST-012"]:
        for _ in range(rng.randint(1, 2)):
            started = datetime(2026, 10, rng.randint(1, 20), rng.choice([7, 11, 16, 20]), 0)
            recovered = started + timedelta(hours=rng.randint(1, 15))
            rows.append(
                {
                    "station_external_id": station_id,
                    "fault_id": f"SYN-FAULT-{event_number:04d}",
                    "fault_type": rng.choice(fault_types),
                    "severity": rng.choice(["LOW", "MEDIUM", "HIGH"]),
                    "started_at": started.isoformat(timespec="minutes"),
                    "recovered_at": recovered.isoformat(timespec="minutes"),
                    "affected_connectors": rng.randint(1, 4),
                    "root_cause": rng.choice(["firmware", "network", "payment_gateway", "thermal_protection"]),
                    **metadata("normal", started.date().isoformat()),
                }
            )
            event_number += 1
    for _ in range(12):
        started = datetime(2026, 10, rng.randint(1, 25), rng.choice([8, 12, 17, 21]), 0)
        recovered = started + timedelta(hours=rng.randint(3, 26))
        rows.append(
            {
                "station_external_id": "SYN-ST-007",
                "fault_id": f"SYN-FAULT-{event_number:04d}",
                "fault_type": rng.choice(fault_types),
                "severity": rng.choice(["MEDIUM", "HIGH"]),
                "started_at": started.isoformat(timespec="minutes"),
                "recovered_at": recovered.isoformat(timespec="minutes"),
                "affected_connectors": rng.randint(2, 8),
                "root_cause": rng.choice(["firmware", "network", "thermal_protection"]),
                **metadata("fault_concentration", started.date().isoformat()),
            }
        )
        event_number += 1
    for index in range(3):
        started = datetime(2025, 6, 3 + index, 10, 0)
        rows.append(
            {
                "station_external_id": "SYN-ST-009",
                "fault_id": f"SYN-FAULT-{event_number:04d}",
                "fault_type": "communication_loss",
                "severity": "MEDIUM",
                "started_at": started.isoformat(timespec="minutes"),
                "recovered_at": (started + timedelta(hours=5)).isoformat(timespec="minutes"),
                "affected_connectors": 2,
                "root_cause": "network",
                **metadata("expired_data", started.date().isoformat(), "expired"),
            }
        )
        event_number += 1
    return rows


def generate_expansion_cases(rng: random.Random) -> list[dict[str, Any]]:
    scenarios = [
        ("high_utilization", "HIGH", 0.93, 3, 240, 180000, 6, 2, "verify transformer capacity"),
        ("high_utilization", "HIGH", 0.88, 1, 320, 210000, 4, 4, "confirm parking lease"),
        ("fault_concentration", "HIGH", 0.67, 12, 180, 145000, 2, 2, "complete root-cause review"),
        ("low_utilization", "LOW", 0.18, 0, 420, 60000, 0, 0, "collect more demand evidence"),
        ("normal", "MEDIUM", 0.59, 2, 360, 125000, 2, 2, "confirm utility quote"),
        ("missing_capacity", "PENDING_DATA", 0.76, 2, "", 130000, 2, 1, "missing electric capacity"),
        ("expired_data", "STALE_DATA", 0.82, 4, 200, 155000, 3, 2, "refresh operating metrics"),
        ("normal", "MEDIUM", 0.51, 1, 500, 195000, 3, 4, "confirm construction schedule"),
    ]
    rows: list[dict[str, Any]] = []
    for index, (scenario, priority, occupancy, fault_count, capacity, budget, fast, slow, preconditions) in enumerate(scenarios, start=1):
        data_as_of = "2025-06-30" if scenario == "expired_data" else "2026-10-15"
        rows.append(
            {
                "case_external_id": f"SYN-EXP-{index:03d}",
                "station_external_id": f"SYN-ST-{index:03d}",
                "case_date": data_as_of,
                "existing_fast_connectors": rng.randint(2, 16),
                "existing_slow_connectors": rng.randint(2, 24),
                "peak_occupancy_rate": f"{occupancy:.3f}",
                "fault_count_30d": fault_count,
                "available_capacity_kw": capacity,
                "requested_budget_usd": budget,
                "proposed_fast_connectors": fast,
                "proposed_slow_connectors": slow,
                "priority": priority,
                "preconditions": preconditions,
                **metadata(scenario, data_as_of, "expired" if scenario == "expired_data" else ("missing_field" if scenario == "missing_capacity" else "current")),
            }
        )
    return rows


def generate_policy_cases() -> list[dict[str, Any]]:
    cases = [
        ("SYN-POL-001", "SYN-CAND-003", "CA-EV-FAST-2026", "2026.1", "municipal", 6, 2, 420000, "PASS", "", "2027-03-31", "normal", "2026-10-15", "current"),
        ("SYN-POL-002", "SYN-CAND-005", "CA-EV-FAST-2026", "2026.1", "private_operator", 4, 4, 360000, "PARTIAL", "site_control;utility_letter", "2027-03-31", "missing_coordinate", "2026-10-15", "missing_coordinate"),
        ("SYN-POL-003", "SYN-CAND-006", "CA-EV-DEPLOY-2025", "2025.4", "private_operator", 2, 2, 150000, "UNKNOWN", "updated_traffic_study", "2026-06-30", "expired_data", "2025-06-30", "expired"),
        ("SYN-POL-004", "SYN-CAND-009", "CA-EV-FAST-2026", "2026.1", "municipal", 8, 2, 500000, "PASS", "", "2027-03-31", "policy_candidate", "2026-10-15", "current"),
    ]
    rows: list[dict[str, Any]] = []
    for item in cases:
        (case_id, candidate_id, policy_code, version, applicant, fast, slow, budget, eligible, missing,
         deadline, scenario, data_as_of, status) = item
        rows.append(
            {
                "policy_case_id": case_id,
                "candidate_site_external_id": candidate_id,
                "region_code": "CA",
                "policy_code": policy_code,
                "policy_version": version,
                "applicant_type": applicant,
                "planned_fast_connectors": fast,
                "planned_slow_connectors": slow,
                "project_budget_usd": budget,
                "eligible_flag": eligible,
                "missing_materials": missing,
                "application_deadline": deadline,
                **metadata(scenario, data_as_of, status),
            }
        )
    return rows


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    rng = random.Random(SEED)
    write_templates()
    candidate_rows = generate_candidates(rng)
    metric_rows = generate_metrics(rng)
    fault_rows = generate_faults(rng)
    expansion_rows = generate_expansion_cases(rng)
    policy_rows = generate_policy_cases()

    generated = {
        "candidate_sites_synthetic_2026-10-29.csv": (TEMPLATES["candidate_sites_template.csv"], candidate_rows),
        "station_metrics_synthetic_2026-10-29.csv": (TEMPLATES["station_metrics_template.csv"], metric_rows),
        "station_faults_synthetic_2026-10-29.csv": (TEMPLATES["station_faults_template.csv"], fault_rows),
        "expansion_cases_synthetic_2026-10-29.csv": (TEMPLATES["expansion_cases_template.csv"], expansion_rows),
        "policy_matching_cases_synthetic_2026-10-29.csv": (TEMPLATES["policy_matching_cases_template.csv"], policy_rows),
    }
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    file_records: list[dict[str, Any]] = []
    for filename, (fields, rows) in generated.items():
        path = RAW_DIR / filename
        csv_write(path, fields, rows)
        file_records.append({"path": str(path.relative_to(PROJECT_ROOT)), "rows": len(rows), "sha256": file_sha256(path), "size_bytes": path.stat().st_size})

    all_rows = [row for _, rows in generated.values() for row in rows]
    assert all(row["source_type"] == "synthetic" for row in all_rows)
    assert all(row["generator_version"] == GENERATOR_VERSION for row in all_rows)
    assert all(row["generated_at"] == GENERATED_AT for row in all_rows)
    assert all(row["synthetic_batch_id"] == BATCH_ID for row in all_rows)

    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "dataset": "ChargeOps synthetic demo business data",
        "source_type": "synthetic",
        "generator_version": GENERATOR_VERSION,
        "seed": SEED,
        "generated_at": GENERATED_AT,
        "synthetic_batch_id": BATCH_ID,
        "region": {"code": "CA", "name": "California"},
        "files": file_records,
        "scenario_coverage": [
            "normal", "high_utilization", "low_utilization", "fault_concentration",
            "missing_coordinate", "missing_capacity", "expired_data", "policy_candidate",
        ],
        "notes": [
            "Synthetic rows are for validation and demonstration only.",
            "They must remain visibly labelled source_type=synthetic and must not be presented as actual operations.",
            "The same seed, generator version and batch timestamp reproduce the same values.",
        ],
    }
    manifest_path = MANIFEST_DIR / "synthetic_demo_2026-10-29.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    checksum_path = MANIFEST_DIR / "synthetic_demo_2026-10-29.sha256"
    checksum_path.write_text("\n".join(f"{item['sha256']}  {item['path']}" for item in file_records) + "\n", encoding="utf-8")
    print(json.dumps({"batch_id": BATCH_ID, "generator_version": GENERATOR_VERSION, "files": file_records, "manifest": str(manifest_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
