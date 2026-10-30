"""RAG Markdown upload, parsing and document metadata services."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT, Settings
from app.schemas.rag import RagDocumentDetail, RagDocumentSummary, RagSection
from app.services.auth import UserContext, record_audit_event


ALLOWED_EXTENSION = ".md"
FILENAME_PATTERN = re.compile(r"^[\w .()\[\]{}@+&,\-]+$", re.UNICODE)
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
LIST_PATTERN = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")
CLAUSE_PATTERN = re.compile(r"^\s*(?:\d+(?:\.\d+)*[.)]?|[（(]?[一二三四五六七八九十百]+[）)])\s+")
TABLE_PATTERN = re.compile(r"^\s*\|.*\|\s*$")
FENCE_PATTERN = re.compile(r"^\s*(```|~~~)")


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def safe_filename(filename: str | None) -> str:
    name = (filename or "").strip()
    if not name or Path(name).name != name or "/" in name or "\\" in name or ".." in name:
        raise ValueError("filename contains an unsafe path")
    if len(name) > 255 or not FILENAME_PATTERN.fullmatch(name):
        raise ValueError("filename contains unsupported characters")
    if Path(name).suffix.lower() != ALLOWED_EXTENSION:
        raise ValueError("only .md files are accepted")
    return name


def normalize_markdown(content: str) -> str:
    text_value = content.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    text_value = "".join(char for char in text_value if char in {"\n", "\t"} or ord(char) >= 32)
    text_value = re.sub(r"\n{3,}", "\n\n", text_value)
    return text_value.strip() + "\n"


def _line_offset(lines: list[str], index: int) -> int:
    return sum(len(line) for line in lines[:index])


def parse_markdown(content: str) -> list[dict[str, Any]]:
    normalized = normalize_markdown(content)
    lines = normalized.splitlines(keepends=True)
    sections: list[dict[str, Any]] = []
    heading_stack: list[tuple[int, str]] = []
    index = 0
    section_index = 0
    while index < len(lines):
        raw = lines[index]
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped:
            index += 1
            continue
        start_line = index
        block_type = "paragraph"
        if FENCE_PATTERN.match(line):
            block_type = "code_fence"
            fence = FENCE_PATTERN.match(line).group(1)[0]  # type: ignore[union-attr]
            index += 1
            while index < len(lines) and not lines[index].lstrip().startswith(fence * 3):
                index += 1
            index = min(index + 1, len(lines))
        else:
            heading_match = HEADING_PATTERN.match(line)
            if heading_match:
                level = len(heading_match.group(1))
                heading = heading_match.group(2).strip()
                heading_stack = [(old_level, value) for old_level, value in heading_stack if old_level < level]
                heading_stack.append((level, heading))
                block_type = "heading"
                index += 1
            elif TABLE_PATTERN.match(line) and index + 1 < len(lines):
                block_type = "table"
                index += 1
                while index < len(lines) and (TABLE_PATTERN.match(lines[index].rstrip("\n")) or not lines[index].strip()):
                    if not lines[index].strip():
                        break
                    index += 1
            elif LIST_PATTERN.match(line):
                block_type = "clause" if CLAUSE_PATTERN.match(line) else "list_item"
                index += 1
            else:
                index += 1
                while index < len(lines):
                    candidate = lines[index].rstrip("\n")
                    if not candidate.strip() or HEADING_PATTERN.match(candidate) or LIST_PATTERN.match(candidate) or FENCE_PATTERN.match(candidate):
                        break
                    index += 1
        end_line = index
        raw_content = "".join(lines[start_line:end_line]).strip()
        if not raw_content:
            continue
        start_char = _line_offset(lines, start_line)
        end_char = start_char + len(raw_content)
        sections.append({
            "section_index": section_index,
            "block_type": block_type,
            "heading_path": " > ".join(value for _, value in heading_stack) or None,
            "content": raw_content,
            "start_char": start_char,
            "end_char": end_char,
            "metadata": {"line_start": start_line + 1, "line_end": end_line},
        })
        section_index += 1
    if not sections:
        raise ValueError("markdown content is empty")
    return sections


def _slug(value: str) -> str:
    result = re.sub(r"[^\w\-]+", "-", value.strip(), flags=re.UNICODE).strip("-").lower()
    return result[:100] or "document"


def _row_to_summary(row: Any) -> RagDocumentSummary:
    return RagDocumentSummary(
        id=int(row["id"]), document_key=row["document_key"], title=row["title"], doc_type=row["doc_type"],
        source_type=row["source_type"], source_url=row["source_url"], original_file=row["original_file"],
        region_code=row["region_code"], version=row["version"], effective_date=row["effective_date"], file_sha256=row["file_sha256"],
        parse_status=row["parse_status"], parse_error=row.get("parse_error"), vector_status=row["vector_status"], embedding_model=row["embedding_model"],
        chunk_count=int(row.get("chunk_count") or 0), uploaded_by=int(row["uploaded_by"]) if row.get("uploaded_by") is not None else None,
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _document_select() -> str:
    return """SELECT id, document_key, title, doc_type, source_type, source_url, original_file,
        region_code, version, effective_date, file_sha256, parse_status, vector_status,
        embedding_model, chunk_count, uploaded_by, parse_error, created_at, updated_at
        FROM rag_document"""


def get_document(session: Session, document_id: int, *, include_sections: bool = True) -> RagDocumentDetail | None:
    row = session.execute(text(f"{_document_select()} WHERE id=:id AND deleted_at IS NULL"), {"id": document_id}).mappings().one_or_none()
    if row is None:
        return None
    summary = _row_to_summary(row)
    sections: list[RagSection] = []
    if include_sections:
        section_rows = session.execute(text("""SELECT id, section_index, block_type, heading_path, content, start_char, end_char, metadata
            FROM rag_document_section WHERE document_id=:document_id ORDER BY section_index"""), {"document_id": document_id}).mappings().all()
        sections = [RagSection(id=int(item["id"]), section_index=int(item["section_index"]), block_type=item["block_type"], heading_path=item["heading_path"], content=item["content"], start_char=int(item["start_char"]), end_char=int(item["end_char"]), metadata=json.loads(item["metadata"]) if isinstance(item["metadata"], str) else (item["metadata"] or {})) for item in section_rows]
    return RagDocumentDetail(**summary.model_dump(), sections=sections, section_count=len(sections))


def list_documents(session: Session, *, doc_type: str | None, parse_status: str | None, vector_status: str | None, region_code: str | None, page: int, page_size: int) -> tuple[list[RagDocumentSummary], int]:
    conditions = ["deleted_at IS NULL"]
    params: dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}
    for value, expression, key in ((doc_type, "doc_type=:doc_type", "doc_type"), (parse_status, "parse_status=:parse_status", "parse_status"), (vector_status, "vector_status=:vector_status", "vector_status"), (region_code, "region_code=:region_code", "region_code")):
        if value:
            conditions.append(expression)
            params[key] = value
    where = " AND ".join(conditions)
    total = int(session.execute(text(f"SELECT COUNT(*) FROM rag_document WHERE {where}"), params).scalar_one())
    rows = session.execute(text(f"{_document_select()} WHERE {where} ORDER BY updated_at DESC, id DESC LIMIT :limit OFFSET :offset"), params).mappings().all()
    return [_row_to_summary(row) for row in rows], total


def _store_path(settings: Settings, document_key: str, filename: str) -> Path:
    base = Path(settings.rag_upload_dir)
    if not base.is_absolute():
        base = PROJECT_ROOT / base
    target_dir = base / document_key
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / filename


def _parse_and_persist(session: Session, document_id: int, text_content: str, user: UserContext, *, retry: bool = False) -> RagDocumentDetail:
    sections = parse_markdown(text_content)
    session.execute(text("DELETE FROM rag_document_section WHERE document_id=:document_id"), {"document_id": document_id})
    now = _now()
    for section in sections:
        session.execute(text("""INSERT INTO rag_document_section
            (document_id, section_index, block_type, heading_path, content, start_char, end_char, metadata, created_at)
            VALUES (:document_id, :section_index, :block_type, :heading_path, :content, :start_char, :end_char, :metadata, :created_at)"""), {
            "document_id": document_id, **section, "metadata": json.dumps(section["metadata"], ensure_ascii=False), "created_at": now,
        })
    session.execute(text("UPDATE rag_document SET parse_status='PARSED', parse_error=NULL, vector_status='PENDING', chunk_count=0, updated_at=:updated_at WHERE id=:id"), {"updated_at": now, "id": document_id})
    record_audit_event(session, action="RAG_DOCUMENT_PARSED" if not retry else "RAG_DOCUMENT_RETRIED", resource_type="rag_document", resource_id=str(document_id), actor_user_id=user.user_id, after_state={"parse_status": "PARSED", "section_count": len(sections)}, commit=True)
    return get_document(session, document_id)  # type: ignore[return-value]


def _mark_failed(session: Session, document_id: int, user: UserContext, error: str, *, retry: bool = False) -> RagDocumentDetail:
    now = _now()
    session.execute(text("UPDATE rag_document SET parse_status='FAILED', parse_error=:parse_error, updated_at=:updated_at WHERE id=:id"), {"parse_error": error[:2000], "updated_at": now, "id": document_id})
    record_audit_event(session, action="RAG_DOCUMENT_PARSE_FAILED", resource_type="rag_document", resource_id=str(document_id), actor_user_id=user.user_id, severity="WARNING", metadata={"error": error, "retry": retry}, commit=True)
    return get_document(session, document_id)  # type: ignore[return-value]


def upload_document(session: Session, settings: Settings, user: UserContext, *, filename: str, content: bytes, title: str | None, doc_type: str, source_type: str, source_url: str | None, region_code: str | None, version: str, effective_date: date | None, document_key: str | None) -> tuple[RagDocumentDetail, bool, str]:
    filename = safe_filename(filename)
    if len(content) > settings.rag_max_file_size_bytes:
        raise ValueError(f"file exceeds {settings.rag_max_file_size_bytes // 1024 // 1024} MB limit")
    try:
        text_content = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Markdown file must be UTF-8 encoded") from exc
    file_hash = sha256_bytes(content)
    existing = session.execute(text("SELECT id FROM rag_document WHERE file_sha256=:file_sha256 AND deleted_at IS NULL ORDER BY id LIMIT 1"), {"file_sha256": file_hash}).scalar_one_or_none()
    if existing is not None:
        detail = get_document(session, int(existing))
        record_audit_event(session, action="RAG_DOCUMENT_DUPLICATE", resource_type="rag_document", resource_id=str(existing), actor_user_id=user.user_id, metadata={"file_sha256": file_hash}, commit=True)
        return detail, True, "文件内容已存在，返回已有文档"
    title = (title or Path(filename).stem).strip()
    if not title or len(title) > 500 or not doc_type or len(doc_type) > 64 or not version or len(version) > 64:
        raise ValueError("title, doc_type and version are required and must be within length limits")
    key = document_key or f"{_slug(title)}-{version}-{file_hash[:12]}"
    key = key[:160]
    key_exists = session.execute(text("SELECT id FROM rag_document WHERE document_key=:document_key AND deleted_at IS NULL"), {"document_key": key}).scalar_one_or_none()
    if key_exists is not None:
        raise ValueError("document_key already exists; use a new version or document key")
    target = _store_path(settings, key, filename)
    target.write_bytes(content)
    now = _now()
    try:
        session.execute(text("""INSERT INTO rag_document
            (document_key, title, doc_type, source_type, source_url, original_file, region_code, version, effective_date,
             file_sha256, parse_status, parse_error, vector_status, embedding_model, chunk_count, uploaded_by, created_at, updated_at)
            VALUES (:document_key, :title, :doc_type, :source_type, :source_url, :original_file, :region_code, :version, :effective_date,
             :file_sha256, 'PARSING', NULL, 'PENDING', NULL, 0, :uploaded_by, :created_at, :updated_at)"""), {
            "document_key": key, "title": title, "doc_type": doc_type, "source_type": source_type, "source_url": source_url or "",
            "original_file": str(target.relative_to(PROJECT_ROOT)).replace("\\", "/"), "region_code": region_code, "version": version,
            "effective_date": effective_date, "file_sha256": file_hash, "uploaded_by": user.user_id, "created_at": now, "updated_at": now,
        })
        document_id = int(session.execute(text("SELECT LAST_INSERT_ID()")).scalar_one())
        session.commit()
    except Exception:
        session.rollback()
        target.unlink(missing_ok=True)
        raise
    try:
        return _parse_and_persist(session, document_id, text_content, user), False, "文档上传并解析成功"
    except Exception as exc:
        session.rollback()
        return _mark_failed(session, document_id, user, str(exc)), False, "文档已保存，但 Markdown 解析失败，可重试"


def retry_document(session: Session, settings: Settings, document_id: int, user: UserContext) -> RagDocumentDetail:
    row = session.execute(text("SELECT original_file FROM rag_document WHERE id=:id AND deleted_at IS NULL"), {"id": document_id}).mappings().one_or_none()
    if row is None:
        raise LookupError("document not found")
    path = PROJECT_ROOT / row["original_file"]
    if not path.exists():
        return _mark_failed(session, document_id, user, "original file is missing", retry=True)
    try:
        text_content = path.read_text(encoding="utf-8-sig")
        session.execute(text("UPDATE rag_document SET parse_status='PARSING', updated_at=:updated_at WHERE id=:id"), {"updated_at": _now(), "id": document_id})
        session.commit()
        return _parse_and_persist(session, document_id, text_content, user, retry=True)
    except Exception as exc:
        session.rollback()
        return _mark_failed(session, document_id, user, str(exc), retry=True)
