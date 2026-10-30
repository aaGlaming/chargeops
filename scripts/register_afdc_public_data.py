"""Download and register an AFDC public EV station snapshot for ChargeOps.

The script intentionally keeps the raw download immutable, creates a normalized
working copy, records a manifest, imports the snapshot into MySQL, and indexes
the accompanying Markdown source note in Chroma. It is safe to re-run for the
same file: the import batch and business rows are keyed by the file SHA-256.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pymysql


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "public"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
MANIFEST_DIR = PROJECT_ROOT / "data" / "manifests"
RAG_DIR = PROJECT_ROOT / "rag_docs" / "business_rules"

SNAPSHOT_DATE = "2026-10-29"
REGION_CODE = "CA"
REGION_NAME = "California"
RAW_NAME = f"afdc_electric_stations_ca_{SNAPSHOT_DATE}.csv"
RAW_PATH = RAW_DIR / RAW_NAME
PROCESSED_PATH = PROCESSED_DIR / f"afdc_electric_stations_ca_{SNAPSHOT_DATE}_normalized.csv"
MANIFEST_PATH = MANIFEST_DIR / f"afdc_electric_stations_ca_{SNAPSHOT_DATE}.json"
DATA_NOTE_PATH = RAG_DIR / "afdc_public_station_data.md"
FIELD_NOTE_PATH = RAG_DIR / "afdc_station_field_dictionary.md"

SOURCE_URL = (
    "https://developer.nlr.gov/api/alt-fuel-stations/v1.csv?"
    "api_key=DEMO_KEY&fuel_type=ELEC&access=public&status=E&state=CA&limit=all"
)
SOURCE_PAGE = "https://afdc.energy.gov/data_download"
FIELD_REFERENCE = "https://afdc.energy.gov/data_download/alt_fuel_stations_format"


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("'\"")
    values.update({key: value for key, value in os.environ.items() if key not in values})
    return values


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_raw() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if RAW_PATH.exists() and RAW_PATH.stat().st_size > 0:
        return
    request = urllib.request.Request(
        SOURCE_URL,
        headers={"User-Agent": "ChargeOps/0.1 public-data-registration"},
    )
    with urllib.request.urlopen(request, timeout=120) as response, RAW_PATH.open("wb") as out:
        while block := response.read(1024 * 1024):
            out.write(block)


def read_rows() -> list[dict[str, str]]:
    with RAW_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def safe_int(value: str | None) -> int:
    if not value:
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def safe_float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalized_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        station_id = safe_int(row.get("ID"))
        if station_id <= 0:
            continue
        level1 = safe_int(row.get("EV Level1 EVSE Num"))
        level2 = safe_int(row.get("EV Level2 EVSE Num"))
        dc_fast = safe_int(row.get("EV DC Fast Count"))
        other = safe_int(row.get("EV Other EVSE Num"))
        output.append(
            {
                "external_station_id": station_id,
                "station_name": row.get("Station Name", "").strip(),
                "street_address": row.get("Street Address", "").strip(),
                "city": row.get("City", "").strip(),
                "state": row.get("State", "").strip(),
                "zip_code": row.get("ZIP", "").strip(),
                "country": row.get("Country", "").strip(),
                "latitude": safe_float(row.get("Latitude")),
                "longitude": safe_float(row.get("Longitude")),
                "status_code": row.get("Status Code", "").strip(),
                "access_code": row.get("Access Code", "").strip(),
                "access_detail_code": row.get("Access Detail Code", "").strip(),
                "facility_type": row.get("Facility Type", "").strip(),
                "ev_network": row.get("EV Network", "").strip() or "Non-Networked",
                "ev_network_web": row.get("EV Network Web", "").strip(),
                "ev_connector_types": row.get("EV Connector Types", "").strip(),
                "level1_count": level1,
                "level2_count": level2,
                "dc_fast_count": dc_fast,
                "other_count": other,
                "total_connector_count": level1 + level2 + dc_fast + other,
                "date_last_confirmed": row.get("Date Last Confirmed", "").strip() or None,
                "updated_at_source": row.get("Updated At", "").strip() or None,
                "open_date": row.get("Open Date", "").strip() or None,
                "funding_sources": row.get("Funding Sources", "").strip(),
            }
        )
    return output


def write_processed(rows: list[dict[str, Any]]) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else []
    with PROCESSED_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_rag_notes(rows: list[dict[str, Any]], raw_hash: str) -> None:
    RAG_DIR.mkdir(parents=True, exist_ok=True)
    total_connectors = sum(row["total_connector_count"] for row in rows)
    networks: dict[str, int] = {}
    for row in rows:
        networks[row["ev_network"]] = networks.get(row["ev_network"], 0) + 1
    top_networks = sorted(networks.items(), key=lambda item: (-item[1], item[0]))[:10]
    network_lines = "\n".join(f"- {name}: {count:,} 个站点" for name, count in top_networks)
    DATA_NOTE_PATH.write_text(
        f"""# AFDC 加州公开电动汽车充电站数据\n\n"
        f"> 本文是 ChargeOps 对公开数据快照的登记说明，不是政策或建设审批结论。\n\n"
        f"## 数据来源\n\n"
        f"- 提供方：美国能源部 Alternative Fuels Data Center（AFDC），数据由 National Laboratory of the Rockies 维护。\n"
        f"- 下载接口：{SOURCE_URL}\n"
        f"- 数据说明：{SOURCE_PAGE}\n"
        f"- 字段参考：{FIELD_REFERENCE}\n"
        f"- 查询条件：燃料类型 `ELEC`、`public`、状态 `E`（Open）、区域 `CA`、当前快照。\n"
        f"- ChargeOps 下载时间：{SNAPSHOT_DATE}（America/Los_Angeles）。\n"
        f"- 原始文件：`data/raw/public/{RAW_NAME}`。\n"
        f"- SHA-256：`{raw_hash}`。\n"
        f"- 使用条款：AFDC 数据下载页声明数据可用于任何目的，但按“现状”提供，使用者需遵守其免责声明和署名限制。\n\n"
        f"## 快照概况\n\n"
        f"- 区域：{REGION_NAME}（`{REGION_CODE}`）\n"
        f"- 公开且开放的电动汽车站点：{len(rows):,} 个\n"
        f"- 连接器数量（按 Level 1、Level 2、DC Fast 和 Other 字段求和）：{total_connectors:,} 个\n"
        f"- 坐标有效率：{sum(1 for row in rows if row['latitude'] is not None and row['longitude'] is not None) / max(len(rows), 1):.2%}\n"
        f"- 主要网络：\n{network_lines}\n\n"
        f"## ChargeOps 业务映射\n\n"
        f"| AFDC 字段 | ChargeOps 字段 | 说明 |\n|---|---|---|\n"
        f"| `ID` | `charging_station.external_station_id` | AFDC 外部站点主键 |\n"
        f"| `Station Name` | `charging_station.station_name` | 站点名称 |\n"
        f"| `Latitude` / `Longitude` | `charging_station.latitude` / `longitude` | 地理坐标 |\n"
        f"| `EV Network` | `operator.operator_name` | 空值统一为 `Non-Networked` |\n"
        f"| `EV Level1 EVSE Num` | `charging_connector(LEVEL1).quantity` | Level 1 数量 |\n"
        f"| `EV Level2 EVSE Num` | `charging_connector(LEVEL2).quantity` | Level 2 数量 |\n"
        f"| `EV DC Fast Count` | `charging_connector(DC_FAST).quantity` | 直流快充数量 |\n"
        f"| `Status Code` / `Access Code` | 站点状态与访问属性 | 只导入当前公开开放快照 |\n\n"
        f"所有业务记录写入 `source_type=public`，并关联导入批次、原始文件、来源 URL 和快照版本。\n\n"
        f"## 使用限制\n\n"
        f"该数据描述公开站点基础设施，不包含 ChargeOps 所需的真实订单、利用率、故障、预算或电力容量。Agent 不得仅凭本快照生成投资、审批或扩容批准结论。\n""",
        encoding="utf-8",
    )
    FIELD_NOTE_PATH.write_text(
        f"""# AFDC 充电站字段字典摘录\n\n"
        f"来源：[{FIELD_REFERENCE}]({FIELD_REFERENCE})。本摘录服务于 ChargeOps 首批加州公开站点导入。\n\n"
        f"| 字段 | 类型 | 用途 |\n|---|---|---|\n"
        f"| `ID` | integer | 外部站点主键，导入时保留 |\n"
        f"| `Station Name` | string | 站点名称 |\n"
        f"| `Street Address`, `City`, `State`, `ZIP` | string | 地址 |\n"
        f"| `Latitude`, `Longitude` | number | 站点坐标；必须校验范围 |\n"
        f"| `Status Code` | string | 站点状态，`E` 表示 Open |\n"
        f"| `Access Code` | string | 访问属性，`public` 表示公开 |\n"
        f"| `EV Network` | string | 运营网络名称 |\n"
        f"| `EV Level1 EVSE Num` | integer | Level 1 充电端口数 |\n"
        f"| `EV Level2 EVSE Num` | integer | Level 2 充电端口数 |\n"
        f"| `EV DC Fast Count` | integer | DC Fast 端口数 |\n"
        f"| `EV Connector Types` | string | 原始连接器类型列表，保留原值 |\n"
        f"| `Date Last Confirmed`, `Updated At` | date/datetime | 数据时效性判断 |\n\n"
        f"原始 CSV 不覆盖、不改写；清洗后的统一字段写入 `data/processed/`。\n""",
        encoding="utf-8",
    )


def mysql_connect(env: dict[str, str]):
    dsn = env.get("MYSQL_DSN", "")
    parsed = urllib.parse.urlparse(dsn.replace("mysql+pymysql://", "mysql://", 1))
    if not parsed.hostname or not parsed.path:
        raise RuntimeError("MYSQL_DSN is missing or invalid")
    return pymysql.connect(
        host=parsed.hostname,
        port=parsed.port or 3306,
        user=urllib.parse.unquote(parsed.username or ""),
        password=urllib.parse.unquote(parsed.password or ""),
        database=parsed.path.lstrip("/"),
        charset="utf8mb4",
        autocommit=False,
    )


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS `import_batch` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `batch_key` VARCHAR(128) NOT NULL,
  `source_type` VARCHAR(32) NOT NULL,
  `source_url` VARCHAR(1000) NOT NULL,
  `source_file` VARCHAR(500) NOT NULL,
  `source_sha256` CHAR(64) NOT NULL,
  `region_code` VARCHAR(16) NOT NULL,
  `data_version` VARCHAR(32) NOT NULL,
  `row_count` INT UNSIGNED NOT NULL DEFAULT 0,
  `license_text` TEXT NULL,
  `status` VARCHAR(32) NOT NULL,
  `created_at` DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_import_batch_key` (`batch_key`),
  KEY `ix_import_batch_region` (`region_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `region` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `region_code` VARCHAR(32) NOT NULL,
  `name` VARCHAR(255) NOT NULL,
  `source_type` VARCHAR(32) NOT NULL,
  `source_url` VARCHAR(1000) NOT NULL,
  `data_version` VARCHAR(32) NOT NULL,
  `import_batch_id` BIGINT UNSIGNED NOT NULL,
  `created_at` DATETIME NOT NULL,
  `updated_at` DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_region_code` (`region_code`),
  KEY `ix_region_batch` (`import_batch_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `operator` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `operator_name` VARCHAR(255) NOT NULL,
  `source_type` VARCHAR(32) NOT NULL,
  `source_url` VARCHAR(1000) NOT NULL,
  `data_version` VARCHAR(32) NOT NULL,
  `import_batch_id` BIGINT UNSIGNED NOT NULL,
  `created_at` DATETIME NOT NULL,
  `updated_at` DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_operator_name_version` (`operator_name`, `data_version`),
  KEY `ix_operator_batch` (`import_batch_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `charging_station` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `external_station_id` BIGINT NOT NULL,
  `region_id` BIGINT UNSIGNED NOT NULL,
  `operator_id` BIGINT UNSIGNED NULL,
  `station_name` VARCHAR(500) NOT NULL,
  `street_address` VARCHAR(500) NULL,
  `city` VARCHAR(255) NULL,
  `state` VARCHAR(32) NULL,
  `zip_code` VARCHAR(32) NULL,
  `country` VARCHAR(8) NULL,
  `latitude` DECIMAL(10,7) NULL,
  `longitude` DECIMAL(10,7) NULL,
  `status_code` VARCHAR(16) NULL,
  `access_code` VARCHAR(32) NULL,
  `access_detail_code` VARCHAR(64) NULL,
  `facility_type` VARCHAR(64) NULL,
  `ev_network_web` VARCHAR(1000) NULL,
  `ev_connector_types` VARCHAR(1000) NULL,
  `total_connector_count` INT UNSIGNED NOT NULL DEFAULT 0,
  `date_last_confirmed` DATE NULL,
  `updated_at_source` VARCHAR(64) NULL,
  `open_date` DATE NULL,
  `funding_sources` VARCHAR(1000) NULL,
  `source_type` VARCHAR(32) NOT NULL,
  `source_url` VARCHAR(1000) NOT NULL,
  `source_file` VARCHAR(500) NOT NULL,
  `data_version` VARCHAR(32) NOT NULL,
  `import_batch_id` BIGINT UNSIGNED NOT NULL,
  `created_at` DATETIME NOT NULL,
  `updated_at` DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_station_snapshot` (`external_station_id`, `data_version`),
  KEY `ix_station_region` (`region_id`),
  KEY `ix_station_operator` (`operator_id`),
  KEY `ix_station_coordinates` (`latitude`, `longitude`),
  KEY `ix_station_batch` (`import_batch_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `charging_connector` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `station_id` BIGINT UNSIGNED NOT NULL,
  `connector_type` VARCHAR(32) NOT NULL,
  `quantity` INT UNSIGNED NOT NULL,
  `source_type` VARCHAR(32) NOT NULL,
  `source_url` VARCHAR(1000) NOT NULL,
  `data_version` VARCHAR(32) NOT NULL,
  `import_batch_id` BIGINT UNSIGNED NOT NULL,
  `created_at` DATETIME NOT NULL,
  `updated_at` DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_connector_snapshot` (`station_id`, `connector_type`, `data_version`),
  KEY `ix_connector_batch` (`import_batch_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `rag_document` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `document_key` VARCHAR(128) NOT NULL,
  `title` VARCHAR(500) NOT NULL,
  `doc_type` VARCHAR(64) NOT NULL,
  `source_type` VARCHAR(32) NOT NULL,
  `source_url` VARCHAR(1000) NOT NULL,
  `original_file` VARCHAR(500) NOT NULL,
  `region_code` VARCHAR(16) NULL,
  `version` VARCHAR(32) NOT NULL,
  `effective_date` DATE NULL,
  `file_sha256` CHAR(64) NOT NULL,
  `parse_status` VARCHAR(32) NOT NULL,
  `vector_status` VARCHAR(32) NOT NULL,
  `embedding_model` VARCHAR(255) NULL,
  `created_at` DATETIME NOT NULL,
  `updated_at` DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_rag_document_key` (`document_key`),
  KEY `ix_rag_document_type_region` (`doc_type`, `region_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `rag_chunk` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `document_id` BIGINT UNSIGNED NOT NULL,
  `chunk_key` VARCHAR(255) NOT NULL,
  `chunk_index` INT UNSIGNED NOT NULL,
  `content` TEXT NOT NULL,
  `start_char` INT UNSIGNED NOT NULL,
  `end_char` INT UNSIGNED NOT NULL,
  `chroma_id` VARCHAR(255) NOT NULL,
  `embedding_model` VARCHAR(255) NOT NULL,
  `created_at` DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_rag_chunk_key` (`chunk_key`),
  KEY `ix_rag_chunk_document` (`document_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def execute_schema(connection) -> None:
    with connection.cursor() as cursor:
        for statement in (part.strip() for part in SCHEMA_SQL.split(";")):
            if statement:
                cursor.execute(statement)


def import_mysql(env: dict[str, str], rows: list[dict[str, Any]], raw_hash: str) -> dict[str, Any]:
    connection = mysql_connect(env)
    now = datetime.now(UTC).replace(tzinfo=None)
    batch_key = f"afdc-public-ca-{SNAPSHOT_DATE}-{raw_hash[:16]}"
    try:
        execute_schema(connection)
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM import_batch WHERE batch_key=%s", (batch_key,))
            existing = cursor.fetchone()
            if existing:
                batch_id = int(existing[0])
            else:
                cursor.execute(
                    """INSERT INTO import_batch
                    (batch_key, source_type, source_url, source_file, source_sha256,
                     region_code, data_version, row_count, license_text, status, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        batch_key,
                        "public",
                        SOURCE_URL,
                        str(RAW_PATH.relative_to(PROJECT_ROOT)),
                        raw_hash,
                        REGION_CODE,
                        SNAPSHOT_DATE,
                        len(rows),
                        "AFDC data may be used for any purpose subject to the download terms and disclaimer.",
                        "IMPORTED",
                        now,
                    ),
                )
                batch_id = cursor.lastrowid

            cursor.execute(
                """INSERT INTO region
                (region_code,name,source_type,source_url,data_version,import_batch_id,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE name=VALUES(name), import_batch_id=VALUES(import_batch_id), updated_at=VALUES(updated_at)""",
                (REGION_CODE, REGION_NAME, "public", SOURCE_URL, SNAPSHOT_DATE, batch_id, now, now),
            )
            cursor.execute("SELECT id FROM region WHERE region_code=%s", (REGION_CODE,))
            region_id = int(cursor.fetchone()[0])

            operator_ids: dict[str, int] = {}
            for name in sorted({str(row["ev_network"]) for row in rows}):
                cursor.execute(
                    """INSERT INTO `operator`
                    (operator_name,source_type,source_url,data_version,import_batch_id,created_at,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE import_batch_id=VALUES(import_batch_id), updated_at=VALUES(updated_at)""",
                    (name, "public", SOURCE_URL, SNAPSHOT_DATE, batch_id, now, now),
                )
                cursor.execute(
                    "SELECT id FROM `operator` WHERE operator_name=%s AND data_version=%s",
                    (name, SNAPSHOT_DATE),
                )
                operator_ids[name] = int(cursor.fetchone()[0])

            station_sql = """INSERT INTO charging_station
                (external_station_id,region_id,operator_id,station_name,street_address,city,state,zip_code,country,
                 latitude,longitude,status_code,access_code,access_detail_code,facility_type,ev_network_web,
                 ev_connector_types,total_connector_count,date_last_confirmed,updated_at_source,open_date,funding_sources,
                 source_type,source_url,source_file,data_version,import_batch_id,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                  region_id=VALUES(region_id), operator_id=VALUES(operator_id), station_name=VALUES(station_name),
                  street_address=VALUES(street_address), city=VALUES(city), state=VALUES(state), zip_code=VALUES(zip_code),
                  country=VALUES(country), latitude=VALUES(latitude), longitude=VALUES(longitude), status_code=VALUES(status_code),
                  access_code=VALUES(access_code), access_detail_code=VALUES(access_detail_code), facility_type=VALUES(facility_type),
                  ev_network_web=VALUES(ev_network_web), ev_connector_types=VALUES(ev_connector_types),
                  total_connector_count=VALUES(total_connector_count), date_last_confirmed=VALUES(date_last_confirmed),
                  updated_at_source=VALUES(updated_at_source), open_date=VALUES(open_date), funding_sources=VALUES(funding_sources),
                  import_batch_id=VALUES(import_batch_id), updated_at=VALUES(updated_at)"""
            connector_sql = """INSERT INTO charging_connector
                (station_id,connector_type,quantity,source_type,source_url,data_version,import_batch_id,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE quantity=VALUES(quantity), import_batch_id=VALUES(import_batch_id), updated_at=VALUES(updated_at)"""
            station_count = 0
            connector_count = 0
            for row in rows:
                dates = []
                for key in ("date_last_confirmed", "open_date"):
                    value = row[key]
                    dates.append(value if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value or "")) else None)
                cursor.execute(
                    station_sql,
                    (
                        row["external_station_id"], region_id, operator_ids[row["ev_network"]], row["station_name"],
                        row["street_address"], row["city"], row["state"], row["zip_code"], row["country"],
                        row["latitude"], row["longitude"], row["status_code"], row["access_code"],
                        row["access_detail_code"], row["facility_type"], row["ev_network_web"], row["ev_connector_types"],
                        row["total_connector_count"], dates[0], row["updated_at_source"], dates[1], row["funding_sources"],
                        "public", SOURCE_URL, str(RAW_PATH.relative_to(PROJECT_ROOT)), SNAPSHOT_DATE, batch_id, now, now,
                    ),
                )
                cursor.execute(
                    "SELECT id FROM charging_station WHERE external_station_id=%s AND data_version=%s",
                    (row["external_station_id"], SNAPSHOT_DATE),
                )
                station_id = int(cursor.fetchone()[0])
                for connector_type, quantity in (
                    ("LEVEL1", row["level1_count"]),
                    ("LEVEL2", row["level2_count"]),
                    ("DC_FAST", row["dc_fast_count"]),
                    ("OTHER", row["other_count"]),
                ):
                    if quantity <= 0:
                        continue
                    cursor.execute(
                        connector_sql,
                        (station_id, connector_type, quantity, "public", SOURCE_URL, SNAPSHOT_DATE, batch_id, now, now),
                    )
                    connector_count += 1
                station_count += 1
        connection.commit()
        return {"batch_id": batch_id, "batch_key": batch_key, "station_rows": station_count, "connector_rows": connector_count}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def split_chunks(text: str, max_chars: int = 1800, overlap: int = 200) -> list[tuple[str, int, int]]:
    chunks: list[tuple[str, int, int]] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            boundary = text.rfind("\n", start + max_chars // 2, end)
            if boundary > start:
                end = boundary
        content = text[start:end].strip()
        if content:
            actual_start = text.find(content, start, end)
            chunks.append((content, actual_start, actual_start + len(content)))
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def embed_texts(env: dict[str, str], texts: list[str]) -> list[list[float]]:
    base_url = env.get("EMBEDDING_BASE_URL", "").rstrip("/")
    api_key = env.get("EMBEDDING_API_KEY", "")
    model = env.get("EMBEDDING_MODEL", "")
    if not base_url or not api_key or not model:
        raise RuntimeError("Embedding configuration is missing; cannot write vectors")
    request = urllib.request.Request(
        base_url + "/embeddings",
        data=json.dumps({"model": model, "input": texts}).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = json.load(response)
    items = sorted(payload["data"], key=lambda item: item.get("index", 0))
    return [item["embedding"] for item in items]


def index_rag(env: dict[str, str], raw_hash: str) -> dict[str, Any]:
    import chromadb

    docs = [(DATA_NOTE_PATH, "AFDC 加州公开电动汽车充电站数据"), (FIELD_NOTE_PATH, "AFDC 充电站字段字典摘录")]
    model = env.get("EMBEDDING_MODEL", "")
    client = chromadb.HttpClient(host=env.get("CHROMA_HOST", "127.0.0.1"), port=int(env.get("CHROMA_PORT", "8001")))
    # Keep Chroma's collection embedding function unset. We always supply
    # explicit external embeddings on upsert/query, so Chroma does not attempt
    # to download its bundled ONNX model on a local machine.
    collection = client.get_or_create_collection(name=env.get("CHROMA_COLLECTION", "chargeops_documents"))
    all_chunks: list[dict[str, Any]] = []
    for path, title in docs:
        text = path.read_text(encoding="utf-8")
        document_key = f"afdc-public-ca-{SNAPSHOT_DATE}-{path.stem}"
        for index, (content, start, end) in enumerate(split_chunks(text)):
            all_chunks.append(
                {
                    "id": f"{document_key}-chunk-{index:04d}",
                    "content": content,
                    "metadata": {
                        "document_key": document_key,
                        "title": title,
                        "doc_type": "public_data_reference",
                        "source_type": "public",
                        "source_url": SOURCE_URL,
                        "region_code": REGION_CODE,
                        "version": SNAPSHOT_DATE,
                        "chunk_index": index,
                        "start_char": start,
                        "end_char": end,
                        "file_sha256": raw_hash if path == DATA_NOTE_PATH else sha256_file(path),
                    },
                }
            )
    embeddings: list[list[float]] = []
    for offset in range(0, len(all_chunks), 16):
        embeddings.extend(embed_texts(env, [item["content"] for item in all_chunks[offset : offset + 16]]))
    collection.upsert(
        ids=[item["id"] for item in all_chunks],
        documents=[item["content"] for item in all_chunks],
        metadatas=[item["metadata"] for item in all_chunks],
        embeddings=embeddings,
    )

    connection = mysql_connect(env)
    now = datetime.now(UTC).replace(tzinfo=None)
    try:
        with connection.cursor() as cursor:
            for path, title in docs:
                document_key = f"afdc-public-ca-{SNAPSHOT_DATE}-{path.stem}"
                file_hash = sha256_file(path)
                cursor.execute(
                    """INSERT INTO rag_document
                    (document_key,title,doc_type,source_type,source_url,original_file,region_code,version,effective_date,
                     file_sha256,parse_status,vector_status,embedding_model,created_at,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE title=VALUES(title), file_sha256=VALUES(file_sha256), vector_status=VALUES(vector_status),
                      embedding_model=VALUES(embedding_model), updated_at=VALUES(updated_at)""",
                    (document_key, title, "public_data_reference", "public", SOURCE_URL,
                     str(path.relative_to(PROJECT_ROOT)), REGION_CODE, SNAPSHOT_DATE, SNAPSHOT_DATE,
                     file_hash, "PARSED", "INDEXED", model, now, now),
                )
                cursor.execute("SELECT id FROM rag_document WHERE document_key=%s", (document_key,))
                document_id = int(cursor.fetchone()[0])
                cursor.execute("DELETE FROM rag_chunk WHERE document_id=%s", (document_id,))
                for item in [item for item in all_chunks if item["metadata"]["document_key"] == document_key]:
                    cursor.execute(
                        """INSERT INTO rag_chunk
                        (document_id,chunk_key,chunk_index,content,start_char,end_char,chroma_id,embedding_model,created_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (document_id, item["id"], item["metadata"]["chunk_index"], item["content"],
                         item["metadata"]["start_char"], item["metadata"]["end_char"], item["id"], model, now),
                    )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {"documents": len(docs), "chunks": len(all_chunks), "collection": collection.name, "embedding_model": model}


def write_manifest(rows: list[dict[str, Any]], raw_hash: str, mysql_result: dict[str, Any], rag_result: dict[str, Any]) -> None:
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "dataset": "AFDC alternative fueling stations",
        "source_type": "public",
        "provider": "U.S. Department of Energy Alternative Fuels Data Center / National Laboratory of the Rockies",
        "source_url": SOURCE_URL,
        "source_page": SOURCE_PAGE,
        "field_reference_url": FIELD_REFERENCE,
        "downloaded_at": f"{SNAPSHOT_DATE} America/Los_Angeles",
        "file_name": RAW_NAME,
        "raw_path": str(RAW_PATH.relative_to(PROJECT_ROOT)),
        "processed_path": str(PROCESSED_PATH.relative_to(PROJECT_ROOT)),
        "file_size_bytes": RAW_PATH.stat().st_size,
        "row_count": len(rows),
        "sha256": raw_hash,
        "query": {"fuel_type": "ELEC", "access": "public", "status": "E", "country": "US", "state": REGION_CODE},
        "region": {"code": REGION_CODE, "name": REGION_NAME},
        "license_and_use": "AFDC download terms state that the data may be used for any purpose, subject to the published disclaimer and attribution restrictions.",
        "external_keys": {"station": "ID", "operator": "EV Network", "connector": "ID + connector_type"},
        "source_type_values": ["public", "user_upload", "synthetic", "agent"],
        "mysql": mysql_result,
        "rag": {**rag_result, "documents": [str(DATA_NOTE_PATH.relative_to(PROJECT_ROOT)), str(FIELD_NOTE_PATH.relative_to(PROJECT_ROOT))]},
        "quality": {
            "valid_coordinate_rows": sum(1 for row in rows if row["latitude"] is not None and row["longitude"] is not None),
            "missing_external_id_rows": 0,
            "duplicate_external_ids": len(rows) - len({row["external_station_id"] for row in rows}),
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    env = load_env()
    download_raw()
    raw_hash = sha256_file(RAW_PATH)
    rows = normalized_rows(read_rows())
    if not rows:
        raise RuntimeError("AFDC file contains no usable station rows")
    write_processed(rows)
    write_rag_notes(rows, raw_hash)
    mysql_result = import_mysql(env, rows, raw_hash)
    rag_result = index_rag(env, raw_hash)
    write_manifest(rows, raw_hash, mysql_result, rag_result)
    print(json.dumps({"raw": str(RAW_PATH), "rows": len(rows), "mysql": mysql_result, "rag": rag_result, "manifest": str(MANIFEST_PATH)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
