"""Create a secret-free, checksummed ChargeOps backup bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pymysql
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def settings() -> dict[str, str]:
    load_dotenv(ROOT / ".env")
    return {key: value for key, value in os.environ.items() if value is not None}


def mysql_parts(env: dict[str, str]) -> dict[str, Any]:
    dsn = env.get("MYSQL_DSN", "")
    parsed = urllib.parse.urlparse(dsn.replace("mysql+pymysql://", "mysql://", 1))
    if not parsed.hostname or not parsed.path:
        raise RuntimeError("MYSQL_DSN is missing or invalid")
    return {
        "host": parsed.hostname,
        "port": parsed.port or 3306,
        "user": urllib.parse.unquote(parsed.username or ""),
        "password": urllib.parse.unquote(parsed.password or ""),
        "database": parsed.path.lstrip("/"),
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def mysql_counts(parts: dict[str, Any]) -> dict[str, int]:
    connection = pymysql.connect(**parts, charset="utf8mb4")
    try:
        with connection.cursor() as cursor:
            result: dict[str, int] = {}
            cursor.execute("SHOW TABLES")
            tables = [str(row[0]) for row in cursor.fetchall()]
            for table in tables:
                cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                result[table] = int(cursor.fetchone()[0])
            return result
    finally:
        connection.close()


def dump_mysql(parts: dict[str, Any], target: Path) -> str:
    mysqldump = shutil.which("mysqldump")
    if mysqldump is None:
        candidate = Path("D:/MySQL/Server8.4/bin/mysqldump.exe")
        if candidate.exists():
            mysqldump = str(candidate)
    if mysqldump is None:
        raise RuntimeError("mysqldump is not installed; install MySQL client tools before backup")
    command = [
        mysqldump,
        "--host", str(parts["host"]),
        "--port", str(parts["port"]),
        "--user", str(parts["user"]),
        "--single-transaction",
        "--routines",
        "--events",
        "--triggers",
        "--hex-blob",
        str(parts["database"]),
    ]
    child_env = os.environ.copy()
    child_env["MYSQL_PWD"] = str(parts["password"])
    with target.open("wb") as handle:
        result = subprocess.run(command, env=child_env, stdout=handle, stderr=subprocess.PIPE, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"mysqldump failed: {result.stderr.decode(errors='replace')[-2000:]}")
    return mysqldump


def copy_tree(source: Path, target: Path) -> dict[str, Any]:
    if not source.exists():
        return {"source": str(source), "exists": False, "files": 0}
    shutil.copytree(source, target, dirs_exist_ok=True)
    return {"source": str(source), "exists": True, "files": sum(1 for item in target.rglob("*") if item.is_file())}


def write_checksums(root: Path) -> int:
    rows: list[str] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file() and item.name != "SHA256SUMS.txt"):
        rows.append(f"{sha256(path)}  {path.relative_to(root).as_posix()}")
    (root / "SHA256SUMS.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return len(rows)


def create_backup(output_root: Path, chroma_dir: Path | None = None) -> dict[str, Any]:
    env = settings()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    bundle = output_root / timestamp
    bundle.mkdir(parents=True, exist_ok=False)
    parts = mysql_parts(env)
    mysql_dir = bundle / "mysql"
    mysql_dir.mkdir()
    counts = mysql_counts(parts)
    dump_tool = dump_mysql(parts, mysql_dir / "chargeops.sql")
    (mysql_dir / "row_counts.json").write_text(json.dumps(counts, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if chroma_dir is None:
        chroma_dir = Path(env.get("CHROMA_DATA_DIR", str(ROOT / "data" / "chroma")))
    artifact_info = {
        "rag_docs": copy_tree(ROOT / "rag_docs", bundle / "artifacts" / "rag_docs"),
        "raw_public": copy_tree(ROOT / "data" / "raw" / "public", bundle / "artifacts" / "data" / "raw" / "public"),
        "raw_synthetic": copy_tree(ROOT / "data" / "raw" / "synthetic", bundle / "artifacts" / "data" / "raw" / "synthetic"),
        "raw_user_upload": copy_tree(ROOT / "data" / "raw" / "user_upload", bundle / "artifacts" / "data" / "raw" / "user_upload"),
        "processed": copy_tree(ROOT / "data" / "processed", bundle / "artifacts" / "data" / "processed"),
        "manifests": copy_tree(ROOT / "data" / "manifests", bundle / "artifacts" / "data" / "manifests"),
        "templates": copy_tree(ROOT / "data" / "templates", bundle / "artifacts" / "data" / "templates"),
        "evals": copy_tree(ROOT / "evals", bundle / "artifacts" / "evals"),
        "chroma": copy_tree(chroma_dir, bundle / "chroma"),
    }
    for relative in (".env.example", "VERSION"):
        source = ROOT / relative
        if source.exists():
            target = bundle / "artifacts" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    metadata = {
        "created_at": datetime.now(UTC).isoformat(),
        "database": {"host": parts["host"], "port": parts["port"], "database": parts["database"], "table_count": len(counts), "row_counts": counts},
        "mysql_dump_tool": dump_tool,
        "chroma_source": str(chroma_dir),
        "artifact_info": artifact_info,
    }
    (bundle / "backup_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    file_count = write_checksums(bundle)
    metadata["file_count"] = file_count
    (bundle / "backup_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Include the final metadata in the checksum list as well.
    write_checksums(bundle)
    return {"backup_dir": str(bundle), "file_count": file_count, "table_count": len(counts), "row_counts": counts}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=ROOT / "backups" / "step39")
    parser.add_argument("--chroma-dir", type=Path)
    args = parser.parse_args()
    result = create_backup(args.output_root, args.chroma_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
