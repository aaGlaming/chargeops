"""Run the Step 37 end-to-end business acceptance flow.

The script uses the running FastAPI/Vite services, real MySQL and Chroma, and
the configured embedding endpoint.  It writes a compact, reproducible report
under ``evals/step37``.  A temporary California bounding polygon is installed
only for the coverage-agent acceptance case because the imported public region
record intentionally has no boundary; the original value is restored in the
finally block.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import pymysql
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "evals" / "step37"
REPORT_PATH = REPORT_DIR / "reports" / "latest.json"
BASE_URL = os.getenv("STEP37_API_URL", "http://127.0.0.1:8000")
FRONTEND_URL = os.getenv("STEP37_FRONTEND_URL", "http://127.0.0.1:5173")
ADMIN_USERNAME = os.getenv("STEP37_ADMIN_USERNAME", "step37-e2e-admin")
ADMIN_PASSWORD = os.getenv("STEP37_ADMIN_PASSWORD", "")
ANALYST_USERNAME = os.getenv("STEP37_ANALYST_USERNAME", "step37-e2e-analyst")
ANALYST_PASSWORD = os.getenv("STEP37_ANALYST_PASSWORD", "")
DATA_VERSION = "2026-10-29"
E2E_STATION_EXTERNAL_ID = "937000371"
E2E_CANDIDATE_EXTERNAL_ID = "STEP37-CAND-001"
E2E_DOCUMENT_KEY = "step37-e2e-policy-2026-10-30"

POLICY_MARKDOWN = """# California charging decision policy

## Coverage and competition

California charging station coverage targets require fast charging access and
service standards. Operator distribution and competition analysis should use
nearby station, connector, and power evidence.

## Expansion

Expansion planning reviews station capacity, utilization rate, fault history,
connector quantities, and construction safety standards before recommending
additional fast chargers.

## Subsidy eligibility

The California subsidy program supports municipal applicants. Required
application materials include a site plan and utility letter. Eligibility,
effective dates, application deadlines, and policy versions must be checked
against the verified policy record. This document is evidence for review and
does not approve construction or subsidy payment.
"""


def _json_response(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text[:500]


class Acceptance:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []
        self.session = requests.Session()
        self.tokens: dict[str, str] = {}
        self.ids: dict[str, Any] = {}

    def check(self, name: str, passed: bool, detail: Any = None) -> None:
        self.checks.append({"name": name, "passed": bool(passed), "detail": detail})

    def request(self, method: str, path: str, *, token: str | None = None, expected: tuple[int, ...] = (200,), **kwargs: Any) -> tuple[int, Any]:
        headers = dict(kwargs.pop("headers", {}) or {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        response = self.session.request(method, f"{BASE_URL}{path}", headers=headers, timeout=240, **kwargs)
        body = _json_response(response)
        self.check(f"api:{method}:{path}", response.status_code in expected, {"status": response.status_code, "body": body if response.status_code not in expected else "ok"})
        return response.status_code, body

    def login(self, username: str, password: str, label: str) -> str:
        status, body = self.request("POST", "/auth/login", expected=(200,), json={"username": username, "password": password})
        token = str(body.get("access_token", "")) if isinstance(body, dict) else ""
        self.check(f"auth:{label}:token", status == 200 and bool(token))
        self.tokens[label] = token
        return token

    def import_csv(self, *, dataset_type: str, filename: str, content: str, label: str) -> dict[str, Any]:
        files = {"file": (filename, content.encode("utf-8"), "text/csv")}
        status, preview = self.request("POST", "/imports/preview", token=self.tokens["admin"], expected=(200,), files=files, data={"dataset_type": dataset_type})
        valid = status == 200 and isinstance(preview, dict) and not preview.get("errors") and preview.get("mapping")
        self.check(f"import:{label}:preview_clean", bool(valid), {"errors": preview.get("errors") if isinstance(preview, dict) else preview})
        request = {
            "dataset_type": dataset_type,
            "file_name": filename,
            "data_version": DATA_VERSION,
            "mapping": preview.get("mapping", {}) if isinstance(preview, dict) else {},
            "rows": preview.get("rows", []) if isinstance(preview, dict) else [],
        }
        status, batch = self.request("POST", "/imports", token=self.tokens["admin"], expected=(201,), json=request)
        self.check(f"import:{label}:mysql_write", status == 201 and isinstance(batch, dict) and batch.get("success_count") == len(request["rows"]))
        self.ids[f"{label}_batch_id"] = batch.get("id") if isinstance(batch, dict) else None
        return batch if isinstance(batch, dict) else {}

    def create_run(self, agent_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = {"agent_type": agent_type, "input_payload": payload, "data_version": DATA_VERSION, "prompt_version": f"{agent_type}-v1", "model_name": "deterministic-supervisor-v1"}
        status, body = self.request("POST", "/agent-runs", token=self.tokens["admin"], expected=(201,), json=request)
        self.check(f"agent:{agent_type}:created", status == 201 and isinstance(body, dict) and body.get("agent_type") == agent_type)
        return body if isinstance(body, dict) else {}

    def execute_run(self, agent_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        run = self.create_run(agent_type, payload)
        run_id = str(run.get("run_id", ""))
        status, detail = self.request("POST", f"/agent-runs/{run_id}/execute", token=self.tokens["admin"], expected=(200,), json={"max_model_calls": 3, "max_tool_calls": 40, "max_loop_iterations": 25, "max_duration_seconds": 180})
        detail = detail if isinstance(detail, dict) else {}
        self.ids[f"{agent_type}_run_id"] = run_id
        self.check(f"agent:{agent_type}:executed", status == 200 and bool(detail.get("status")), {"status": detail.get("status"), "stop_reason": detail.get("stop_reason")})
        snapshot = detail.get("state_snapshot") if isinstance(detail.get("state_snapshot"), dict) else {}
        tool_calls = detail.get("tool_calls") if isinstance(detail.get("tool_calls"), list) else []
        tool_names = {str(item.get("tool_name")) for item in tool_calls if isinstance(item, dict)}
        self.check(f"agent:{agent_type}:mysql_trace", any(name.endswith(".query") for name in tool_names))
        self.check(f"agent:{agent_type}:rag_trace", "rag.search" in tool_names and "rag.evidence.verify" in tool_names)
        self.check(f"agent:{agent_type}:evidence", bool(snapshot.get("evidence")))
        self.check(f"agent:{agent_type}:calculation", any(name in tool_names for name in ("coverage.analyze", "competition.analyze", "site.score", "expansion.plan", "policy.match")))
        return detail

    def create_and_export_report(self, agent_type: str, detail: dict[str, Any]) -> dict[str, Any]:
        run_id = str(detail.get("run_id", ""))
        status, report = self.request("POST", "/reports", token=self.tokens["admin"], expected=(201,), json={"run_id": run_id, "title": f"Step 37 {agent_type} acceptance report"})
        report = report if isinstance(report, dict) else {}
        self.check(f"report:{agent_type}:created", status == 201 and bool(report.get("report_id")))
        self.check(f"report:{agent_type}:evidence", bool(report.get("business_data")) and bool(report.get("rag_evidence")))
        report_id = str(report.get("report_id", ""))
        export_status, exported = self.request("GET", f"/reports/{report_id}/export?format=json", token=self.tokens["admin"], expected=(200,))
        self.check(f"report:{agent_type}:export", export_status == 200 and isinstance(exported, dict) and exported.get("run_id") == run_id)
        self.ids[f"{agent_type}_report_id"] = report_id
        return report


def set_test_boundary() -> tuple[Any, Any]:
    load_dotenv(ROOT / ".env")
    dsn = os.environ["MYSQL_DSN"].replace("mysql+pymysql://", "mysql://")
    from urllib.parse import urlparse

    parsed = urlparse(dsn)
    connection = pymysql.connect(host=parsed.hostname, port=parsed.port or 3306, user=parsed.username, password=parsed.password, database=parsed.path.strip("/"))
    cursor = connection.cursor()
    cursor.execute("SELECT boundary_geojson FROM region WHERE region_code='CA' ORDER BY id LIMIT 1")
    original = cursor.fetchone()[0]
    polygon = json.dumps({"type": "Polygon", "coordinates": [[[-125.0, 32.0], [-114.0, 32.0], [-114.0, 42.0], [-125.0, 42.0], [-125.0, 32.0]]]})
    cursor.execute("UPDATE region SET boundary_geojson=%s WHERE region_code='CA'", (polygon,))
    connection.commit()
    return connection, original


def restore_boundary(connection: Any, original: Any) -> None:
    cursor = connection.cursor()
    cursor.execute("UPDATE region SET boundary_geojson=%s WHERE region_code='CA'", (original,))
    connection.commit()
    connection.close()


def ui_acceptance(acceptance: Acceptance) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        acceptance.check("frontend:playwright_available", False, str(exc))
        return
    edge = os.getenv("STEP37_BROWSER", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    console_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=edge)
        page = browser.new_page()
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.goto(f"{FRONTEND_URL}/login", wait_until="networkidle")
        acceptance.check("frontend:login:rendered", "登录 ChargeOps" in page.content())
        page.get_by_label("用户名").fill(ADMIN_USERNAME)
        page.get_by_label("密码").fill(ADMIN_PASSWORD)
        page.get_by_role("button", name="进入工作台").click()
        page.wait_for_url("**/dashboard", timeout=20000)
        page.wait_for_load_state("networkidle")
        acceptance.check("frontend:login:redirect_dashboard", page.url.endswith("/dashboard"))
        routes = ["/dashboard", "/imports", "/regions", "/stations", "/candidates", "/agents/coverage", "/agents/competition", "/agents/site-selection", "/agents/expansion", "/agents/policy", "/rag", "/runs", "/audit", "/monitoring"]
        for route in routes:
            page.goto(f"{FRONTEND_URL}{route}", wait_until="networkidle")
            page.reload(wait_until="networkidle")
            acceptance.check(f"frontend:route:{route}", page.url.endswith(route) and "ChargeOps" in page.content())
        console_errors.clear()
        page.goto(f"{FRONTEND_URL}/missing-route", wait_until="networkidle")
        acceptance.check("frontend:empty_route_redirect", page.url.endswith("/dashboard"))
        browser.close()
        acceptance.check("frontend:console_errors", not console_errors, console_errors[:10])


def run() -> dict[str, Any]:
    acceptance = Acceptance()
    if not ADMIN_PASSWORD or not ANALYST_PASSWORD:
        acceptance.check("precondition:test_credentials", False, "STEP37_ADMIN_PASSWORD and STEP37_ANALYST_PASSWORD are required")
        return {"status": "FAIL", "checks": acceptance.checks}
    admin = acceptance.login(ADMIN_USERNAME, ADMIN_PASSWORD, "admin")
    analyst = acceptance.login(ANALYST_USERNAME, ANALYST_PASSWORD, "analyst")
    acceptance.request("GET", "/health", token=admin, expected=(200,))
    ready_status, ready = acceptance.request("GET", "/ready", token=admin, expected=(200, 503))
    ready_checks = ready.get("checks", []) if isinstance(ready, dict) else []
    ready_names = {str(item.get("service")): str(item.get("status")) for item in ready_checks if isinstance(item, dict)}
    acceptance.check("ready:mysql_chroma_embedding", ready_names.get("mysql") == "ok" and ready_names.get("chroma") == "ok" and ready_names.get("embedding") == "ok", ready_names)
    acceptance.check("ready:chat_degraded_is_explicit", ready_status == 200 or ready_names.get("chat") == "down", ready_names)
    acceptance.request("GET", "/auth/me", token=admin, expected=(200,))
    acceptance.request("GET", "/regions", token=admin, expected=(200,))
    acceptance.request("GET", "/stations/map-points?region_code=CA&limit=20", token=admin, expected=(200,))

    station_csv = "external_station_id,station_name,latitude,longitude,station_status,access_type,data_version\n" + f"{E2E_STATION_EXTERNAL_ID},Step 37 E2E Public Station,34.0500,-118.2500,OPEN,PUBLIC,{DATA_VERSION}\n"
    acceptance.import_csv(dataset_type="stations", filename="step37-public-stations.csv", content=station_csv, label="public_station")
    station_status, station_list = acceptance.request("GET", f"/stations?source_type=user_upload&data_version={DATA_VERSION}&page_size=50", token=admin, expected=(200,))
    station_items = station_list.get("items", []) if isinstance(station_list, dict) else []
    station = next((item for item in station_items if str(item.get("external_station_id")) == E2E_STATION_EXTERNAL_ID), None)
    acceptance.check("public_station:map_and_list", station_status == 200 and station is not None)

    candidate_csv = "candidate_site_external_id,site_name,region_code,latitude,longitude,budget_usd,data_as_of\n" + f"{E2E_CANDIDATE_EXTERNAL_ID},Step 37 E2E Candidate,CA,34.0522,-118.2437,125000,2026-10-15\n"
    acceptance.import_csv(dataset_type="candidates", filename="step37-candidates.csv", content=candidate_csv, label="candidate_site")
    candidate_status, candidates = acceptance.request("GET", "/candidate-sites?source_type=user_upload&page_size=100", token=admin, expected=(200,))
    candidate_items = candidates.get("items", []) if isinstance(candidates, dict) else []
    candidate = next((item for item in candidate_items if item.get("external_candidate_id") == E2E_CANDIDATE_EXTERNAL_ID), None)
    acceptance.check("candidate_site:page_and_mapping", candidate_status == 200 and candidate is not None)
    candidate_id = int(candidate.get("id")) if candidate else 39
    acceptance.ids["candidate_id"] = candidate_id

    files = {"file": ("step37-policy.md", POLICY_MARKDOWN.encode("utf-8"), "text/markdown")}
    upload_status, upload = acceptance.request("POST", "/rag/documents", token=admin, expected=(200, 201), files=files, data={"title": "Step 37 E2E policy", "doc_type": "business_rule", "source_type": "user_upload", "region_code": "CA", "version": "step37-2026-10-30", "effective_date": "2026-10-01", "document_key": E2E_DOCUMENT_KEY})
    document = upload.get("document", {}) if isinstance(upload, dict) else {}
    document_id = int(document.get("id")) if document.get("id") else None
    acceptance.ids["document_id"] = document_id
    acceptance.check("rag:upload_parse", upload_status in (200, 201) and document.get("parse_status") == "PARSED")
    chunk_status, chunk = acceptance.request("POST", f"/rag/documents/{document_id}/chunks/preview", token=admin, expected=(200,), json={"target_tokens": 128, "overlap_tokens": 16})
    chunk_batch_key = chunk.get("batch", {}).get("batch_key") if isinstance(chunk, dict) else None
    acceptance.check("rag:chunk_preview", chunk_status == 200 and bool(chunk_batch_key) and bool(chunk.get("chunks")))
    embedding_status, embedding = acceptance.request("POST", f"/rag/documents/{document_id}/embeddings", token=admin, expected=(200,), json={"chunk_batch_key": chunk_batch_key, "force": True})
    acceptance.check("rag:vector_index", embedding_status == 200 and embedding.get("batch", {}).get("status") == "COMPLETED")
    search_status, search = acceptance.request("POST", "/rag/search", token=admin, expected=(200,), json={"query": "California charging station expansion subsidy utilization application materials", "top_k": 5, "doc_type": "business_rule", "region_code": "CA", "version": "step37-2026-10-30", "use_vector": True, "use_keyword": True, "use_rerank": False})
    acceptance.check("rag:search_and_original", search_status == 200 and search.get("status") == "HIT" and bool(search.get("hits")))
    if search.get("hits"):
        hit = search["hits"][0]
        source_status, source = acceptance.request("GET", f"/rag/documents/{hit['document_id']}/source?start_char={hit.get('start_char', 0)}&end_char={hit.get('end_char', 200)}", token=admin, expected=(200,))
        acceptance.check("rag:original_fragment", source_status == 200 and bool(source.get("content")))

    boundary_connection = None
    original_boundary = None
    try:
        boundary_connection, original_boundary = set_test_boundary()
        station_id = int(station.get("id")) if station else 101880
        agent_details: dict[str, dict[str, Any]] = {}
        agent_details["coverage_gap"] = acceptance.execute_run("coverage_gap", {"region_code": "CA", "charger_type": "FAST", "coverage_radius_km": 5, "threshold": 0.8, "fast_ratio_threshold": 0.3, "time_gap_occupancy_threshold": 0.85, "stale_after_days": 365, "analysis_date": "2026-10-30"})
        agent_details["competition"] = acceptance.execute_run("competition", {"latitude": 34.0522, "longitude": -118.2437, "radius_km": 5, "distance_decay_km": 2, "service_gap_connector_threshold": 4, "service_gap_power_kw_threshold": 150, "analysis_date": "2026-10-30"})
        agent_details["site_selection"] = acceptance.execute_run("site_selection", {"candidate_site_ids": [candidate_id], "nearby_radius_km": 5, "stale_after_days": 90, "min_data_confidence": 0.5})
        agent_details["expansion"] = acceptance.execute_run("expansion", {"station_ids": [station_id], "analysis_date": "2026-10-30", "start_date": "2026-10-01", "end_date": "2026-10-30", "occupancy_target": 0.75, "high_occupancy_threshold": 0.9, "fast_connector_power_kw": 60, "fast_connector_cost_usd": 25000, "slow_connector_cost_usd": 5000})
        agent_details["policy_matching"] = acceptance.execute_run("policy_matching", {"region_code": "CA", "subject_type": "MUNICIPAL", "candidate_site_ids": [39], "project_budget_usd": 125000, "planned_scale_kw": 400, "available_materials": ["site_plan"], "planned_date": "2026-10-30", "stale_after_days": 365})
        expected_statuses = {"coverage_gap": "COMPLETED", "competition": "COMPLETED", "site_selection": "COMPLETED", "expansion": "WAITING_CONFIRMATION", "policy_matching": "COMPLETED"}
        for agent_type, expected in expected_statuses.items():
            actual = agent_details[agent_type].get("status")
            acceptance.check(f"agent:{agent_type}:business_status", actual == expected, {"expected": expected, "actual": actual})
        expansion = agent_details["expansion"]
        expansion_run_id = expansion.get("run_id")
        acceptance.check("agent:expansion:manual_gate", expansion.get("status") == "WAITING_CONFIRMATION" and expansion.get("confirmation_status") == "PENDING")
        expansion_report_confirmed = False
        for agent_type, detail in agent_details.items():
            if detail.get("status") in {"COMPLETED", "WAITING_CONFIRMATION"}:
                report = acceptance.create_and_export_report(agent_type, detail)
                report_id = report.get("report_id")
                if report.get("status") == "WAITING_CONFIRMATION":
                    confirmation_status, confirmed = acceptance.request("POST", f"/reports/{report_id}/confirmation", token=admin, expected=(200,), json={"decision": "APPROVE", "comment": "Step 37 acceptance approval after evidence review"})
                    acceptance.check(f"report:{agent_type}:manual_confirmation", confirmation_status == 200 and confirmed.get("status") == "APPROVED")
                    expansion_report_confirmed = expansion_report_confirmed or agent_type == "expansion"
        if expansion_run_id and not expansion_report_confirmed:
            confirmation_status, confirmed_run = acceptance.request("POST", f"/agent-runs/{expansion_run_id}/confirmation", token=admin, expected=(200,), json={"decision": "APPROVE", "comment": "Step 37 acceptance approval after expansion evidence review"})
            acceptance.check("agent:expansion:approved_after_confirmation", confirmation_status == 200 and confirmed_run.get("status") == "COMPLETED")
        elif expansion_run_id:
            acceptance.check("agent:expansion:approved_after_confirmation", True)
    finally:
        if boundary_connection is not None:
            restore_boundary(boundary_connection, original_boundary)

    acceptance.request("GET", "/agent-runs", token=admin, expected=(200,))
    acceptance.request("GET", "/audit-logs?page=1&page_size=10", token=admin, expected=(200,))
    acceptance.request("GET", "/monitoring/overview", token=admin, expected=(200,))
    acceptance.request("GET", "/agents/contracts?agent_type=coverage_gap", token=admin, expected=(200,))
    denied_status, denied = acceptance.request("POST", "/agent-runs", token=analyst, expected=(403,), json={"agent_type": "expansion", "input_payload": {"station_ids": [101880]}})
    acceptance.check("permissions:analyst_cannot_start_expansion", denied_status == 403 and isinstance(denied, dict) and denied.get("error_code") == "PERMISSION_DENIED")
    ui_acceptance(acceptance)
    failed = [item for item in acceptance.checks if not item["passed"]]
    return {"suite": "chargeops-step37-e2e-business-acceptance", "suite_version": "step37-2026-10-30", "generated_at": datetime.now().astimezone().isoformat(), "status": "PASS" if not failed else "FAIL", "checks": {"total": len(acceptance.checks), "passed": len(acceptance.checks) - len(failed), "failed": len(failed)}, "ids": acceptance.ids, "failed_checks": failed, "all_checks": acceptance.checks}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    report = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "checks": report["checks"], "output": str(args.output)}, ensure_ascii=False))
    return 1 if args.strict and report["status"] != "PASS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
