"""Roll back all rows associated with a ChargeOps import batch."""

from __future__ import annotations

import argparse
import os
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pymysql


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"


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


def connect(env: dict[str, str]):
    parsed = urllib.parse.urlparse(env["MYSQL_DSN"].replace("mysql+pymysql://", "mysql://", 1))
    return pymysql.connect(
        host=parsed.hostname,
        port=parsed.port or 3306,
        user=urllib.parse.unquote(parsed.username or ""),
        password=urllib.parse.unquote(parsed.password or ""),
        database=parsed.path.lstrip("/"),
        charset="utf8mb4",
        autocommit=False,
    )


def now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def table_has_batch_column(cursor, table: str) -> bool:
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=%s AND column_name='import_batch_id'",
        (table,),
    )
    return bool(cursor.fetchone()[0])


def resolve_batch(cursor, batch_id: int | None, batch_key: str | None) -> tuple[int, dict[str, Any]]:
    if batch_id is not None:
        cursor.execute("SELECT * FROM import_batch WHERE id=%s", (batch_id,))
    else:
        cursor.execute("SELECT * FROM import_batch WHERE batch_key=%s", (batch_key,))
    row = cursor.fetchone()
    if not row:
        raise ValueError("import batch not found")
    columns = [item[0] for item in cursor.description]
    return int(row[0]), dict(zip(columns, row))


def main() -> int:
    parser = argparse.ArgumentParser()
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--batch-id", type=int)
    selector.add_argument("--batch-key")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm", action="store_true", help="required for a destructive rollback")
    args = parser.parse_args()
    if not args.dry_run and not args.confirm:
        raise SystemExit("Refusing rollback without --confirm; use --dry-run to preview")

    connection = connect(load_env())
    delete_order = [
        "import_row_error", "audit_log", "tool_call", "site_score", "expansion_plan",
        "station_fault_event", "station_operation_metric", "charging_connector", "charging_station",
        "candidate_site", "policy_condition", "operator", "region",
    ]
    try:
        with connection.cursor() as cursor:
            resolved_id, batch = resolve_batch(cursor, args.batch_id, args.batch_key)
            counts: dict[str, int] = {}
            for table in delete_order:
                if table_has_batch_column(cursor, table):
                    cursor.execute(f"SELECT COUNT(*) FROM `{table}` WHERE import_batch_id=%s", (resolved_id,))
                    counts[table] = int(cursor.fetchone()[0])
            if args.dry_run:
                print({"batch_id": resolved_id, "batch_key": batch.get("batch_key"), "status": batch.get("status"), "rows_by_table": counts, "total_rows": sum(counts.values()), "dry_run": True})
                return 0
            for table in delete_order:
                if table_has_batch_column(cursor, table):
                    cursor.execute(f"DELETE FROM `{table}` WHERE import_batch_id=%s", (resolved_id,))
            cursor.execute(
                "UPDATE import_batch SET status='ROLLED_BACK',rollback_status='ROLLED_BACK',completed_at=%s WHERE id=%s",
                (now_utc(), resolved_id),
            )
        connection.commit()
        print({"batch_id": resolved_id, "batch_key": batch.get("batch_key"), "rows_deleted": counts, "total_rows_deleted": sum(counts.values()), "status": "ROLLED_BACK"})
        return 0
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
