"""Restore a ChargeOps backup into an isolated directory and verify it."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
from pathlib import Path
from typing import Any

import pymysql
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_checksums(backup: Path) -> tuple[int, list[str]]:
    failures: list[str] = []
    rows = [line.strip() for line in (backup / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in rows:
        expected, relative = row.split("  ", 1)
        path = backup / relative
        if not path.exists() or sha256(path) != expected:
            failures.append(relative)
    return len(rows), failures


def mysql_parts() -> dict[str, Any]:
    load_dotenv(ROOT / ".env")
    parsed = urllib.parse.urlparse(os.environ["MYSQL_DSN"].replace("mysql+pymysql://", "mysql://", 1))
    return {"host": parsed.hostname, "port": parsed.port or 3306, "user": urllib.parse.unquote(parsed.username or ""), "password": urllib.parse.unquote(parsed.password or ""), "database": parsed.path.lstrip("/")}


def mysql_shadow_restore(backup: Path, prefix: str) -> dict[str, Any]:
    parts = mysql_parts()
    sql = (backup / "mysql" / "chargeops.sql").read_text(encoding="utf-8", errors="replace")
    connection = pymysql.connect(**parts, charset="utf8mb4", autocommit=True)
    shadow_tables: list[str] = []
    try:
        with connection.cursor() as cursor:
            cursor.execute("SHOW TABLES")
            tables = [str(row[0]) for row in cursor.fetchall()]
            for table in sorted(tables, key=len, reverse=True):
                shadow = f"{prefix}{table}"
                shadow_tables.append(shadow)
                sql = sql.replace(f"`{table}`", f"`{shadow}`")
            sql = sql.replace("CONSTRAINT `", f"CONSTRAINT `{prefix}")
            sql = re.sub(r"/\*![0-9]+ SET @@SESSION.SQL_LOG_BIN= 0 \*/;", "", sql)
            sql_path = backup.parent / f"{prefix}shadow.sql"
            sql_path.write_text("SET FOREIGN_KEY_CHECKS=0;\n" + sql + "\nSET FOREIGN_KEY_CHECKS=1;\n", encoding="utf-8")
        mysql = shutil.which("mysql") or "D:/MySQL/Server8.4/bin/mysql.exe"
        child_env = os.environ.copy()
        child_env["MYSQL_PWD"] = str(parts["password"])
        result = subprocess.run([mysql, "--host", str(parts["host"]), "--port", str(parts["port"]), "--user", str(parts["user"]), str(parts["database"])], input=sql_path.read_bytes(), env=child_env, capture_output=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode(errors="replace")[-3000:])
        counts: dict[str, int] = {}
        with connection.cursor() as cursor:
            for table in shadow_tables:
                cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=%s", (table,))
                if not cursor.fetchone()[0]:
                    continue
                cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                counts[table] = int(cursor.fetchone()[0])
            cursor.execute("SET FOREIGN_KEY_CHECKS=0")
            for table in shadow_tables:
                if table in counts:
                    cursor.execute(f"DROP TABLE `{table}`")
            cursor.execute("SET FOREIGN_KEY_CHECKS=1")
        sql_path.unlink(missing_ok=True)
        return {"status": "VERIFIED", "shadow_table_count": len(counts), "shadow_row_counts": counts}
    finally:
        connection.close()


def restore_artifacts(backup: Path, restore_dir: Path) -> dict[str, Any]:
    if restore_dir.exists():
        shutil.rmtree(restore_dir)
    restore_dir.mkdir(parents=True)
    shutil.copytree(backup / "artifacts", restore_dir / "artifacts")
    shutil.copytree(backup / "chroma", restore_dir / "chroma")
    shutil.copy2(backup / "mysql" / "chargeops.sql", restore_dir / "mysql-chargeops.sql")
    shutil.copy2(backup / "mysql" / "row_counts.json", restore_dir / "mysql-row_counts.json")
    return {"files": sum(1 for item in restore_dir.rglob("*") if item.is_file()), "path": str(restore_dir)}


def chroma_restore_check(restore_dir: Path) -> dict[str, Any]:
    chroma_dir = restore_dir / "chroma"
    files = [path for path in chroma_dir.rglob("*") if path.is_file()]
    if not files:
        return {"status": "NO_FILES", "files": 0}
    result: dict[str, Any] = {"status": "FILES_VERIFIED", "files": len(files), "bytes": sum(path.stat().st_size for path in files)}
    chroma = shutil.which("chroma") or "D:/Configuration/python/Scripts/chroma.exe"
    if Path(chroma).exists():
        port = 18003
        process = subprocess.Popen([chroma, "run", "--path", str(chroma_dir), "--host", "127.0.0.1", "--port", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            heartbeat = False
            for _ in range(30):
                try:
                    response = requests.get(f"http://127.0.0.1:{port}/api/v2/heartbeat", timeout=1)
                    heartbeat = response.ok
                    if heartbeat:
                        break
                except requests.RequestException:
                    time.sleep(1)
            collections = requests.get(f"http://127.0.0.1:{port}/api/v2/tenants/default_tenant/databases/default_database/collections", timeout=5) if heartbeat else None
            result["server_status"] = "VERIFIED" if heartbeat and collections is not None and collections.ok else "FAILED"
            result["collection_count"] = len(collections.json()) if collections is not None and collections.ok else 0
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
    else:
        result["server_status"] = "SKIPPED"
    return result


def api_restore_verification(api_url: str, username: str, password: str) -> dict[str, Any]:
    session = requests.Session()
    login = session.post(f"{api_url.rstrip('/')}/auth/login", json={"username": username, "password": password}, timeout=20)
    login.raise_for_status()
    token = login.json().get("access_token")
    headers = {"Authorization": f"Bearer {token}"}
    search = session.post(
        f"{api_url.rstrip('/')}/rag/search",
        headers=headers,
        json={"query": "charging station data field dictionary", "top_k": 3, "use_vector": True, "use_keyword": True, "use_rerank": False},
        timeout=240,
    )
    search.raise_for_status()
    search_body = search.json()
    if search_body.get("status") != "HIT" or not search_body.get("hits"):
        raise RuntimeError("restored RAG verification returned no hit")
    candidates = session.get(f"{api_url.rstrip('/')}/candidate-sites?source_type=synthetic&page_size=1", headers=headers, timeout=20)
    candidates.raise_for_status()
    candidate_items = candidates.json().get("items", [])
    if not candidate_items:
        raise RuntimeError("no candidate site available for restored Agent verification")
    candidate_id = int(candidate_items[0]["id"])
    created = session.post(
        f"{api_url.rstrip('/')}/agent-runs",
        headers=headers,
        json={"agent_type": "site_selection", "data_version": "2026-10-29", "prompt_version": "site-selection-v1", "model_name": "deterministic-supervisor-v1", "input_payload": {"candidate_site_ids": [candidate_id], "nearby_radius_km": 5, "stale_after_days": 365, "min_data_confidence": 0.5}},
        timeout=20,
    )
    created.raise_for_status()
    run_id = created.json()["run_id"]
    executed = session.post(
        f"{api_url.rstrip('/')}/agent-runs/{run_id}/execute",
        headers=headers,
        json={"max_model_calls": 3, "max_tool_calls": 40, "max_loop_iterations": 25, "max_duration_seconds": 180},
        timeout=240,
    )
    executed.raise_for_status()
    detail = executed.json()
    if detail.get("status") not in {"COMPLETED", "BLOCKED"}:
        raise RuntimeError(f"restored Agent verification returned {detail.get('status')}")
    return {"status": "VERIFIED", "rag_status": search_body.get("status"), "rag_hit_count": len(search_body.get("hits", [])), "agent_type": "site_selection", "agent_run_id": run_id, "agent_status": detail.get("status")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup_dir", type=Path)
    parser.add_argument("--restore-dir", type=Path, required=True)
    parser.add_argument("--prefix", default="step39_restore_")
    parser.add_argument("--api-url")
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    backup = args.backup_dir.resolve()
    files, checksum_failures = verify_checksums(backup)
    restored = restore_artifacts(backup, args.restore_dir.resolve())
    mysql_result = mysql_shadow_restore(backup, args.prefix)
    chroma_result = chroma_restore_check(args.restore_dir.resolve())
    api_result: dict[str, Any] = {"status": "SKIPPED", "reason": "credentials not provided"}
    if args.api_url and args.username and args.password:
        api_result = api_restore_verification(args.api_url, args.username, args.password)
    chroma_ok = chroma_result["status"] == "FILES_VERIFIED" and chroma_result.get("server_status") in {"VERIFIED", "SKIPPED"}
    report = {"status": "PASS" if not checksum_failures and mysql_result["status"] == "VERIFIED" and chroma_ok and api_result["status"] in {"VERIFIED", "SKIPPED"} else "FAIL", "backup_dir": str(backup), "restore": restored, "checksum": {"files": files, "failures": checksum_failures}, "mysql": mysql_result, "chroma": chroma_result, "api_verification": api_result}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
