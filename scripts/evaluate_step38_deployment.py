"""Validate Windows and Docker deployment assets for Step 38.

The evaluator always checks the repository deployment contract and, when the
local services are running, checks health, readiness, Swagger and the Vue
shell. Docker runtime checks are reported as an explicit limitation when the
Docker CLI is not installed on the host.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "evals" / "step38" / "reports" / "latest.json"


class Evaluation:
    def __init__(self, api_url: str, frontend_url: str) -> None:
        self.api_url = api_url.rstrip("/")
        self.frontend_url = frontend_url.rstrip("/")
        self.checks: list[dict[str, Any]] = []
        self.skipped: list[dict[str, Any]] = []

    def check(self, name: str, passed: bool, detail: Any = None) -> None:
        self.checks.append({"name": name, "passed": bool(passed), "detail": detail})

    def skip(self, name: str, detail: Any) -> None:
        self.skipped.append({"name": name, "skipped": True, "detail": detail})

    def http(self, method: str, url: str, expected: tuple[int, ...] = (200,)) -> tuple[int, Any]:
        try:
            response = requests.request(method, url, timeout=10)
            try:
                body: Any = response.json()
            except ValueError:
                body = response.text[:500]
            self.check(f"http:{method}:{url}", response.status_code in expected, {"status": response.status_code})
            return response.status_code, body
        except requests.RequestException as exc:
            self.check(f"http:{method}:{url}", False, str(exc))
            return 0, None


def run(api_url: str, frontend_url: str) -> dict[str, Any]:
    evaluation = Evaluation(api_url, frontend_url)
    required_files = [
        "compose.yaml",
        "backend/Dockerfile",
        "frontend/Dockerfile",
        "frontend/nginx.conf",
        "scripts/start_windows.ps1",
        "scripts/stop_windows.ps1",
        "scripts/init_database.ps1",
        "scripts/import_sample_data.ps1",
        "scripts/index_rag_documents.ps1",
    ]
    for relative in required_files:
        path = ROOT / relative
        evaluation.check(f"asset:{relative}", path.is_file() and path.stat().st_size > 0)

    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    for token in ("mysql:", "chroma:", "backend:", "frontend:", "healthcheck:", "mysql-data:", "chroma-data:", "rag-data:", "logs-data:"):
        evaluation.check(f"compose:contains:{token}", token in compose)
    evaluation.check("compose:backend-build-context-root", "context: ." in compose and "dockerfile: backend/Dockerfile" in compose)
    evaluation.check("compose:dependency-health-order", "condition: service_healthy" in compose)
    evaluation.check("compose:restart-policy", compose.count("restart: unless-stopped") == 4)

    docker_path = shutil.which("docker")
    if docker_path:
        result = subprocess.run([docker_path, "compose", "-f", str(ROOT / "compose.yaml"), "config"], capture_output=True, text=True, timeout=30)
        evaluation.check("docker:compose-config", result.returncode == 0, result.stderr[-1000:])
    else:
        evaluation.skip("docker:compose-config", "Docker CLI 未安装，已完成 compose 静态契约检查")
        evaluation.skip("docker:runtime-up-build-restart-volume", "Docker Desktop/CLI 不可用，未启动或修改容器")

    evaluation.http("GET", f"{api_url}/health")
    ready_status, ready = evaluation.http("GET", f"{api_url}/ready", expected=(200, 503))
    if isinstance(ready, dict):
        raw_checks = ready.get("checks", {})
        checks = ({str(item.get("service")): str(item.get("status")) for item in raw_checks if isinstance(item, dict)}
                  if isinstance(raw_checks, list) else {str(key): str(value) for key, value in raw_checks.items()})
        evaluation.check("api:ready:database-and-chroma", checks.get("mysql") == "ok" and checks.get("chroma") == "ok", checks)
        evaluation.check("api:ready:status-explicit", ready_status in (200, 503))
    else:
        evaluation.check("api:ready:body", False, ready)
    evaluation.http("GET", f"{api_url}/docs")
    evaluation.http("GET", f"{frontend_url}/")
    healthz_status, _ = evaluation.http("GET", f"{frontend_url}/healthz", expected=(200, 404))
    evaluation.check("frontend:healthz-or-vite-dev", healthz_status in (200, 404))
    for route in ("/dashboard", "/agents/coverage", "/agents/competition", "/agents/site-selection", "/agents/expansion", "/agents/policy"):
        status, body = evaluation.http("GET", f"{frontend_url}{route}")
        evaluation.check(f"frontend:route:{route}", status == 200 and isinstance(body, str) and "ChargeOps" in body)

    failed = [item for item in evaluation.checks if not item["passed"]]
    status = "PASS" if not failed and not evaluation.skipped else ("PASS_WITH_LIMITATION" if not failed else "FAIL")
    return {
        "suite": "chargeops-step38-deployment-acceptance",
        "suite_version": "step38-2026-10-30",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "status": status,
        "checks": {"total": len(evaluation.checks), "passed": len(evaluation.checks) - len(failed), "failed": len(failed), "skipped": len(evaluation.skipped)},
        "failed_checks": failed,
        "skipped_checks": evaluation.skipped,
        "all_checks": evaluation.checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--frontend-url", default="http://127.0.0.1:5173")
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    report = run(args.api_url, args.frontend_url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "checks": report["checks"], "output": str(args.output)}, ensure_ascii=False))
    return 1 if args.strict and report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
