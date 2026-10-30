"""Initialize and migrate the ChargeOps MySQL schema without deleting data."""

from __future__ import annotations

import hashlib
import os
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path

import pymysql


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
DDL_PATH = PROJECT_ROOT / "infra" / "mysql" / "001_initial_schema.sql"


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
        autocommit=True,
    )


def strip_sql_comments(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))


def table_exists(cursor, table: str) -> bool:
    cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=%s", (table,))
    return bool(cursor.fetchone()[0])


def column_exists(cursor, table: str, column: str) -> bool:
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=%s AND column_name=%s",
        (table, column),
    )
    return bool(cursor.fetchone()[0])


def index_exists(cursor, table: str, index_name: str) -> bool:
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name=%s AND index_name=%s",
        (table, index_name),
    )
    return bool(cursor.fetchone()[0])


def ensure_column(cursor, table: str, column: str, definition: str) -> None:
    if not column_exists(cursor, table, column):
        cursor.execute(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}")


def ensure_compatibility_columns(cursor) -> None:
    # Step 5 created a minimal import_batch table. These additions make it
    # usable by the full Step 9 import/rollback workflow.
    if table_exists(cursor, "import_batch"):
        for column, definition in {
            "dataset_type": "VARCHAR(64) NULL AFTER batch_key",
            "success_count": "INT UNSIGNED NOT NULL DEFAULT 0 AFTER row_count",
            "failed_count": "INT UNSIGNED NOT NULL DEFAULT 0 AFTER success_count",
            "skipped_count": "INT UNSIGNED NOT NULL DEFAULT 0 AFTER failed_count",
            "rollback_status": "VARCHAR(32) NOT NULL DEFAULT 'NOT_REQUESTED' AFTER status",
            "failure_report_file": "VARCHAR(500) NULL AFTER rollback_status",
            "completed_at": "DATETIME NULL AFTER created_at",
        }.items():
            ensure_column(cursor, "import_batch", column, definition)
    if table_exists(cursor, "charging_station"):
        ensure_column(cursor, "charging_station", "external_station_key", "VARCHAR(128) NULL AFTER external_station_id")
        cursor.execute("UPDATE charging_station SET external_station_key=CAST(external_station_id AS CHAR) WHERE external_station_key IS NULL")
        if not index_exists(cursor, "charging_station", "uq_station_external_key_version"):
            cursor.execute("CREATE UNIQUE INDEX uq_station_external_key_version ON charging_station (external_station_key, data_version)")
    if table_exists(cursor, "region"):
        for column, definition in {
            "parent_region_id": "BIGINT UNSIGNED NULL AFTER region_code",
            "region_type": "VARCHAR(64) NULL AFTER name",
            "country_code": "CHAR(2) NULL AFTER region_type",
            "boundary_geojson": "JSON NULL AFTER country_code",
            "source_file": "VARCHAR(500) NULL AFTER source_url",
            "deleted_at": "DATETIME NULL AFTER updated_at",
        }.items():
            ensure_column(cursor, "region", column, definition)
    if table_exists(cursor, "expansion_plan"):
        ensure_column(cursor, "expansion_plan", "external_case_id", "VARCHAR(128) NULL AFTER id")
        if not index_exists(cursor, "expansion_plan", "uq_expansion_case_version"):
            cursor.execute("CREATE UNIQUE INDEX uq_expansion_case_version ON expansion_plan (external_case_id, data_version)")
    if table_exists(cursor, "rag_document"):
        for column, definition in {
            "chunk_count": "INT UNSIGNED NOT NULL DEFAULT 0",
            "uploaded_by": "BIGINT UNSIGNED NULL",
            "deleted_at": "DATETIME NULL",
            "parse_error": "VARCHAR(2000) NULL",
        }.items():
            ensure_column(cursor, "rag_document", column, definition)
    if table_exists(cursor, "rag_chunk"):
        for column, definition in {
            "batch_id": "BIGINT UNSIGNED NULL AFTER document_id",
            "heading_path": "VARCHAR(1000) NULL",
            "chroma_collection": "VARCHAR(255) NULL",
            "metadata": "JSON NULL",
        }.items():
            ensure_column(cursor, "rag_chunk", column, definition)


def ensure_workflow_tables(cursor) -> None:
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS schema_migration (
            version VARCHAR(128) NOT NULL PRIMARY KEY,
            checksum CHAR(64) NOT NULL,
            applied_at DATETIME NOT NULL,
            description VARCHAR(500) NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS import_row_error (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            import_batch_id BIGINT UNSIGNED NOT NULL,
            source_file VARCHAR(500) NOT NULL,
            source_row_number INT UNSIGNED NULL,
            field_name VARCHAR(128) NULL,
            error_code VARCHAR(128) NOT NULL,
            error_message VARCHAR(1000) NOT NULL,
            raw_payload JSON NULL,
            created_at DATETIME NOT NULL,
            resolved_at DATETIME NULL,
            PRIMARY KEY (id),
            KEY ix_import_error_batch (import_batch_id),
            KEY ix_import_error_code (error_code),
            CONSTRAINT fk_import_error_batch FOREIGN KEY (import_batch_id) REFERENCES import_batch (id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS user_data_scope (
            user_id BIGINT UNSIGNED NOT NULL,
            region_code VARCHAR(32) NOT NULL DEFAULT '*',
            dataset_type VARCHAR(64) NOT NULL,
            can_read TINYINT(1) NOT NULL DEFAULT 1,
            can_write TINYINT(1) NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            PRIMARY KEY (user_id, region_code, dataset_type),
            KEY ix_user_scope_dataset (dataset_type, region_code),
            CONSTRAINT fk_user_scope_user FOREIGN KEY (user_id) REFERENCES users (id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS rag_document_section (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            document_id BIGINT UNSIGNED NOT NULL,
            section_index INT UNSIGNED NOT NULL,
            block_type VARCHAR(32) NOT NULL,
            heading_path VARCHAR(1000) NULL,
            content MEDIUMTEXT NOT NULL,
            start_char INT UNSIGNED NOT NULL,
            end_char INT UNSIGNED NOT NULL,
            metadata JSON NULL,
            created_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            UNIQUE KEY uq_rag_section_order (document_id, section_index),
            KEY ix_rag_section_type (document_id, block_type),
            CONSTRAINT fk_rag_section_document FOREIGN KEY (document_id) REFERENCES rag_document (id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS rag_chunk_batch (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            document_id BIGINT UNSIGNED NOT NULL,
            batch_key VARCHAR(160) NOT NULL,
            document_version VARCHAR(64) NOT NULL,
            cleaning_version VARCHAR(64) NOT NULL,
            target_tokens INT UNSIGNED NOT NULL,
            overlap_tokens INT UNSIGNED NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'PREVIEW',
            chunk_count INT UNSIGNED NOT NULL DEFAULT 0,
            invalid_count INT UNSIGNED NOT NULL DEFAULT 0,
            created_by BIGINT UNSIGNED NULL,
            created_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            UNIQUE KEY uq_rag_chunk_batch_key (batch_key),
            KEY ix_rag_chunk_batch_document (document_id, created_at),
            CONSTRAINT fk_rag_chunk_batch_document FOREIGN KEY (document_id) REFERENCES rag_document (id),
            CONSTRAINT fk_rag_chunk_batch_user FOREIGN KEY (created_by) REFERENCES users (id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS rag_embedding_batch (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            batch_key VARCHAR(255) NOT NULL,
            document_id BIGINT UNSIGNED NOT NULL,
            chunk_batch_id BIGINT UNSIGNED NULL,
            document_version VARCHAR(64) NOT NULL,
            embedding_model VARCHAR(255) NOT NULL,
            model_version VARCHAR(255) NULL,
            parameters JSON NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
            requested_count INT UNSIGNED NOT NULL DEFAULT 0,
            success_count INT UNSIGNED NOT NULL DEFAULT 0,
            failed_count INT UNSIGNED NOT NULL DEFAULT 0,
            pending_retry_count INT UNSIGNED NOT NULL DEFAULT 0,
            error_message VARCHAR(2000) NULL,
            created_by BIGINT UNSIGNED NULL,
            started_at DATETIME NULL,
            completed_at DATETIME NULL,
            created_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            UNIQUE KEY uq_rag_embedding_batch_key (batch_key),
            KEY ix_rag_embedding_batch_document (document_id, created_at),
            KEY ix_rag_embedding_batch_status (status, created_at),
            CONSTRAINT fk_rag_embedding_batch_document FOREIGN KEY (document_id) REFERENCES rag_document (id),
            CONSTRAINT fk_rag_embedding_batch_chunks FOREIGN KEY (chunk_batch_id) REFERENCES rag_chunk_batch (id),
            CONSTRAINT fk_rag_embedding_batch_user FOREIGN KEY (created_by) REFERENCES users (id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS rag_embedding_item (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            embedding_batch_id BIGINT UNSIGNED NOT NULL,
            chunk_id BIGINT UNSIGNED NOT NULL,
            chunk_key VARCHAR(255) NOT NULL,
            chroma_id VARCHAR(255) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
            attempt_count INT UNSIGNED NOT NULL DEFAULT 0,
            vector_dimension INT UNSIGNED NULL,
            error_code VARCHAR(128) NULL,
            error_message VARCHAR(2000) NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            UNIQUE KEY uq_rag_embedding_item_batch_chunk (embedding_batch_id, chunk_id),
            KEY ix_rag_embedding_item_status (embedding_batch_id, status),
            CONSTRAINT fk_rag_embedding_item_batch FOREIGN KEY (embedding_batch_id) REFERENCES rag_embedding_batch (id),
            CONSTRAINT fk_rag_embedding_item_chunk FOREIGN KEY (chunk_id) REFERENCES rag_chunk (id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS rag_search_log (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            run_id CHAR(36) NOT NULL,
            query_text VARCHAR(2000) NOT NULL,
            rewritten_query VARCHAR(2000) NOT NULL,
            agent_scenario VARCHAR(128) NULL,
            filters JSON NULL,
            vector_count INT UNSIGNED NOT NULL DEFAULT 0,
            keyword_count INT UNSIGNED NOT NULL DEFAULT 0,
            hit_count INT UNSIGNED NOT NULL DEFAULT 0,
            hit_chunk_ids JSON NULL,
            status VARCHAR(32) NOT NULL,
            actor_user_id BIGINT UNSIGNED NULL,
            created_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            UNIQUE KEY uq_rag_search_run_id (run_id),
            KEY ix_rag_search_created (created_at),
            KEY ix_rag_search_status (status),
            CONSTRAINT fk_rag_search_actor FOREIGN KEY (actor_user_id) REFERENCES users (id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS agent_run_event (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            run_id CHAR(36) NOT NULL,
            sequence_no INT UNSIGNED NOT NULL,
            event_type VARCHAR(32) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
            provider VARCHAR(128) NULL,
            model_name VARCHAR(255) NULL,
            confirmation_type VARCHAR(64) NULL,
            input_summary JSON NULL,
            output_summary JSON NULL,
            error_code VARCHAR(128) NULL,
            retryable TINYINT(1) NOT NULL DEFAULT 0,
            duration_ms INT UNSIGNED NULL,
            actor_user_id BIGINT UNSIGNED NULL,
            started_at DATETIME NULL,
            finished_at DATETIME NULL,
            created_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            UNIQUE KEY uq_agent_event_sequence (run_id, sequence_no),
            KEY ix_agent_event_type_status (event_type, status),
            CONSTRAINT fk_agent_event_run FOREIGN KEY (run_id) REFERENCES agent_run (run_id),
            CONSTRAINT fk_agent_event_actor FOREIGN KEY (actor_user_id) REFERENCES users (id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
    )


def main() -> int:
    env = load_env()
    ddl = strip_sql_comments(DDL_PATH.read_text(encoding="utf-8"))
    checksum = hashlib.sha256(ddl.encode("utf-8")).hexdigest()
    connection = connect(env)
    try:
        with connection.cursor() as cursor:
            for statement in ddl.split(";"):
                statement = statement.strip()
                if statement:
                    cursor.execute(statement)
            ensure_compatibility_columns(cursor)
            ensure_workflow_tables(cursor)
            cursor.execute("SELECT COUNT(*) FROM schema_migration WHERE version=%s", ("001_target_model",))
            if cursor.fetchone()[0] == 0:
                cursor.execute(
                    "INSERT INTO schema_migration(version,checksum,applied_at,description) VALUES (%s,%s,%s,%s)",
                    ("001_target_model", checksum, datetime.now(UTC).replace(tzinfo=None), "Step 8 target model and Step 9 import workflow"),
                )
            cursor.execute("SELECT COUNT(*) FROM schema_migration WHERE version=%s", ("002_auth_data_scope",))
            if cursor.fetchone()[0] == 0:
                cursor.execute(
                    "INSERT INTO schema_migration(version,checksum,applied_at,description) VALUES (%s,%s,%s,%s)",
                    ("002_auth_data_scope", hashlib.sha256(b"user_data_scope").hexdigest(), datetime.now(UTC).replace(tzinfo=None), "Step 11 user data scope table"),
                )
            cursor.execute("SELECT COUNT(*) FROM schema_migration WHERE version=%s", ("003_rag_document_sections",))
            if cursor.fetchone()[0] == 0:
                cursor.execute(
                    "INSERT INTO schema_migration(version,checksum,applied_at,description) VALUES (%s,%s,%s,%s)",
                    ("003_rag_document_sections", hashlib.sha256(b"rag_document_compatibility_and_sections").hexdigest(), datetime.now(UTC).replace(tzinfo=None), "Step 14 RAG document compatibility and parsed sections"),
                )
            cursor.execute("SELECT COUNT(*) FROM schema_migration WHERE version=%s", ("004_rag_chunk_batches",))
            if cursor.fetchone()[0] == 0:
                cursor.execute(
                    "INSERT INTO schema_migration(version,checksum,applied_at,description) VALUES (%s,%s,%s,%s)",
                    ("004_rag_chunk_batches", hashlib.sha256(b"rag_chunk_batches_cleaning_preview").hexdigest(), datetime.now(UTC).replace(tzinfo=None), "Step 15 chunk cleaning, preview and historical batches"),
                )
            cursor.execute("SELECT COUNT(*) FROM schema_migration WHERE version=%s", ("005_rag_embedding_batches",))
            if cursor.fetchone()[0] == 0:
                cursor.execute(
                    "INSERT INTO schema_migration(version,checksum,applied_at,description) VALUES (%s,%s,%s,%s)",
                    ("005_rag_embedding_batches", hashlib.sha256(b"rag_embedding_chroma_batches").hexdigest(), datetime.now(UTC).replace(tzinfo=None), "Step 16 embedding and Chroma indexing batches"),
                )
            cursor.execute("SELECT COUNT(*) FROM schema_migration WHERE version=%s", ("006_rag_search_log",))
            if cursor.fetchone()[0] == 0:
                cursor.execute(
                    "INSERT INTO schema_migration(version,checksum,applied_at,description) VALUES (%s,%s,%s,%s)",
                    ("006_rag_search_log", hashlib.sha256(b"rag_search_retrieval_log").hexdigest(), datetime.now(UTC).replace(tzinfo=None), "Step 17 RAG vector and keyword retrieval logs"),
                )
            cursor.execute("SELECT COUNT(*) FROM schema_migration WHERE version=%s", ("007_agent_state_contracts",))
            if cursor.fetchone()[0] == 0:
                cursor.execute(
                    "INSERT INTO schema_migration(version,checksum,applied_at,description) VALUES (%s,%s,%s,%s)",
                    ("007_agent_state_contracts", hashlib.sha256(b"agent_state_tool_contracts_events").hexdigest(), datetime.now(UTC).replace(tzinfo=None), "Step 18 Agent state, tool, model and confirmation event contracts"),
                )
            cursor.execute("SELECT COUNT(*) FROM schema_migration WHERE version=%s", ("008_coverage_gap_boundary",))
            if cursor.fetchone()[0] == 0:
                cursor.execute(
                    "INSERT INTO schema_migration(version,checksum,applied_at,description) VALUES (%s,%s,%s,%s)",
                    ("008_coverage_gap_boundary", hashlib.sha256(b"coverage_gap_region_boundary_compatibility").hexdigest(), datetime.now(UTC).replace(tzinfo=None), "Step 21 coverage gap region boundary compatibility columns"),
                )
            cursor.execute("SHOW TABLES")
            tables = [row[0] for row in cursor.fetchall()]
        print({"database": env.get("MYSQL_DSN", "").split("@")[-1], "table_count": len(tables), "migrations": ["001_target_model", "002_auth_data_scope", "003_rag_document_sections", "004_rag_chunk_batches", "005_rag_embedding_batches", "006_rag_search_log", "007_agent_state_contracts", "008_coverage_gap_boundary"], "workflow_tables": ["schema_migration", "import_row_error", "user_data_scope", "rag_document_section", "rag_chunk_batch", "rag_embedding_batch", "rag_embedding_item", "rag_search_log", "agent_run_event"]})
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
