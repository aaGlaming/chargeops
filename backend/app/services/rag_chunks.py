"""Markdown cleaning, structural chunking and chunk preview services."""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT, Settings
from app.schemas.rag import RagChunkBatchListResponse, RagChunkBatchResponse, RagChunkBatchSummary, RagChunkItem
from app.services.auth import UserContext, record_audit_event
from app.services.rag_documents import CLAUSE_PATTERN, parse_markdown


CLEANING_VERSION = "clean-v1"
DEFAULT_TARGET_TOKENS = 800
DEFAULT_OVERLAP_TOKENS = 120


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def estimate_tokens(value: str) -> int:
    """Use a deterministic character estimate until the embedding tokenizer is configured."""
    return max(1, math.ceil(len(value) / 4))


def clean_markdown(content: str) -> str:
    """Normalize text while keeping headings, clauses, tables and list boundaries."""
    value = content.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
    value = "".join(char for char in value if char in {"\n", "\t"} or ord(char) >= 32)
    lines = []
    for raw_line in value.split("\n"):
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        lines.append(line)

    # Repeated page headers/footers are removed only at the document edges.
    counts: dict[str, int] = {}
    for line in lines:
        if line:
            counts[line] = counts.get(line, 0) + 1
    edge_indexes = set(range(min(5, len(lines)))) | set(range(max(0, len(lines) - 5), len(lines)))
    cleaned: list[str] = []
    for index, line in enumerate(lines):
        if line and counts.get(line, 0) >= 2 and index in edge_indexes:
            continue
        cleaned.append(line)

    value = "\n".join(cleaned)
    value = re.sub(r"\n{3,}", "\n\n", value).strip()
    if not value:
        raise ValueError("markdown content is empty after cleaning")
    return value + "\n"


def _split_long_section(section: dict[str, Any], target_chars: int, overlap_chars: int) -> list[dict[str, Any]]:
    content = section["content"]
    if len(content) <= target_chars:
        return [section]
    pieces: list[dict[str, Any]] = []
    position = 0
    while position < len(content):
        limit = min(len(content), position + target_chars)
        cut = content.rfind("\n", position + max(1, target_chars // 2), limit + 1)
        if cut <= position:
            cut = limit
        piece = content[position:cut].strip()
        if piece:
            leading = len(content[position:cut]) - len(content[position:cut].lstrip())
            start = int(section["start_char"]) + position + leading
            end = start + len(piece)
            pieces.append({**section, "content": piece, "start_char": start, "end_char": end})
        if cut >= len(content):
            break
        position = max(position + 1, cut - overlap_chars)
    return pieces


def _build_chunks(cleaned_text: str, target_tokens: int, overlap_tokens: int) -> list[dict[str, Any]]:
    target_chars = target_tokens * 4
    overlap_chars = min(max(0, overlap_tokens * 4), max(0, target_chars - 1))
    # Keep a small margin for the separator and line trimming performed by Markdown parsing.
    overlap_capacity = max(1, target_chars - overlap_chars - 8)
    sections = parse_markdown(cleaned_text)
    atomic_sections: list[dict[str, Any]] = []
    for section in sections:
        # Leave room for the overlap prefix in every chunk after the first one.
        atomic_sections.extend(_split_long_section(section, overlap_capacity, overlap_chars))

    chunks: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_length = 0
    previous_content = ""
    for section in atomic_sections:
        separator_length = 2 if current else 0
        proposed_length = current_length + separator_length + len(section["content"])
        capacity = target_chars if not chunks else overlap_capacity
        if current and proposed_length > capacity:
            chunks.append(_chunk_from_sections(current, previous_content, overlap_chars))
            previous_content = chunks[-1]["content"]
            current = []
            current_length = 0
        current.append(section)
        current_length += (2 if len(current) > 1 else 0) + len(section["content"])
    if current:
        chunks.append(_chunk_from_sections(current, previous_content, overlap_chars))
    return chunks


def _chunk_from_sections(sections: list[dict[str, Any]], previous_content: str, overlap_chars: int) -> dict[str, Any]:
    body = "\n\n".join(item["content"] for item in sections).strip()
    if previous_content and overlap_chars:
        overlap = previous_content[-overlap_chars:]
        body = f"{overlap}\n\n{body}".strip()
    start = int(sections[0]["start_char"])
    end = int(sections[-1]["end_char"])
    if previous_content and overlap_chars:
        start = max(0, start - min(overlap_chars, len(previous_content)))
    return {
        "content": body,
        "start_char": start,
        "end_char": end,
        "heading_path": sections[0].get("heading_path"),
        "source_sections": sections,
    }


def _validate_chunk(chunk: dict[str, Any], target_tokens: int) -> list[str]:
    issues: list[str] = []
    content = chunk["content"]
    if not content.strip():
        issues.append("EMPTY_CHUNK")
    if estimate_tokens(content) > target_tokens:
        issues.append("OVER_TARGET_TOKENS")
    if not chunk.get("heading_path"):
        issues.append("MISSING_HEADING_PATH")
    source_text = "\n".join(item["content"] for item in chunk.get("source_sections", []))
    if CLAUSE_PATTERN.search(source_text) and not CLAUSE_PATTERN.search(content):
        issues.append("MISSING_CLAUSE_NUMBER")
    return issues


def _document_source(session: Session, document_id: int) -> dict[str, Any] | None:
    row = session.execute(text("""SELECT id, document_key, version, original_file, parse_status
        FROM rag_document WHERE id=:id AND deleted_at IS NULL"""), {"id": document_id}).mappings().one_or_none()
    return dict(row) if row else None


def _batch_summary(row: Any) -> RagChunkBatchSummary:
    return RagChunkBatchSummary(
        id=int(row["id"]), batch_key=row["batch_key"], document_id=int(row["document_id"]),
        document_version=row["document_version"], cleaning_version=row["cleaning_version"],
        target_tokens=int(row["target_tokens"]), overlap_tokens=int(row["overlap_tokens"]), status=row["status"],
        chunk_count=int(row.get("chunk_count") or 0), invalid_count=int(row.get("invalid_count") or 0),
        created_by=int(row["created_by"]) if row.get("created_by") is not None else None, created_at=row["created_at"],
    )


def _chunk_item(row: Any, document_version: str) -> RagChunkItem:
    metadata = json.loads(row["metadata"]) if isinstance(row.get("metadata"), str) else (row.get("metadata") or {})
    issues = list(metadata.get("validation_issues") or [])
    return RagChunkItem(
        id=int(row["id"]), chunk_id=row["chunk_key"], chunk_index=int(row["chunk_index"]),
        heading_path=row.get("heading_path"), content=row["content"], start_char=int(row["start_char"]),
        end_char=int(row["end_char"]), estimated_tokens=int(metadata.get("estimated_tokens") or estimate_tokens(row["content"])),
        document_version=document_version, validation_status="INVALID" if issues else "VALID", validation_issues=issues,
        original_href=f"/rag/documents/{int(row['document_id'])}/source?start_char={int(row['start_char'])}&end_char={int(row['end_char'])}", metadata=metadata,
    )


def get_chunk_batch(session: Session, document_id: int, *, batch_key: str | None = None) -> RagChunkBatchResponse | None:
    params: dict[str, Any] = {"document_id": document_id}
    condition = "document_id=:document_id"
    if batch_key:
        condition += " AND batch_key=:batch_key"
        params["batch_key"] = batch_key
    else:
        condition += " AND id=(SELECT MAX(id) FROM rag_chunk_batch WHERE document_id=:document_id)"
    batch = session.execute(text(f"SELECT * FROM rag_chunk_batch WHERE {condition}"), params).mappings().one_or_none()
    if batch is None:
        return None
    chunks = session.execute(text("""SELECT id, document_id, chunk_key, chunk_index, heading_path, content, start_char, end_char, metadata
        FROM rag_chunk WHERE batch_id=:batch_id ORDER BY chunk_index"""), {"batch_id": batch["id"]}).mappings().all()
    return RagChunkBatchResponse(batch=_batch_summary(batch), chunks=[_chunk_item(row, batch["document_version"]) for row in chunks])


def list_chunk_batches(session: Session, document_id: int) -> RagChunkBatchListResponse:
    rows = session.execute(text("SELECT * FROM rag_chunk_batch WHERE document_id=:document_id ORDER BY id DESC"), {"document_id": document_id}).mappings().all()
    return RagChunkBatchListResponse(items=[_batch_summary(row) for row in rows])


def create_chunk_batch(
    session: Session,
    settings: Settings,
    user: UserContext,
    document_id: int,
    *,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    status: str = "PREVIEW",
) -> RagChunkBatchResponse:
    if overlap_tokens >= target_tokens:
        raise ValueError("overlap_tokens must be smaller than target_tokens")
    document = _document_source(session, document_id)
    if document is None:
        raise LookupError("document not found")
    if document["parse_status"] != "PARSED":
        raise ValueError("document must be PARSED before chunking")
    path = PROJECT_ROOT / document["original_file"]
    if not path.exists():
        raise ValueError("original file is missing")
    cleaned = clean_markdown(path.read_text(encoding="utf-8-sig"))
    chunks = _build_chunks(cleaned, target_tokens, overlap_tokens)
    batch_key = f"{document['document_key']}-{CLEANING_VERSION}-{target_tokens}-{overlap_tokens}-{_now().strftime('%Y%m%d%H%M%S%f')}"
    now = _now()
    invalid_count = sum(1 for chunk in chunks if _validate_chunk(chunk, target_tokens))
    session.execute(text("""INSERT INTO rag_chunk_batch
        (document_id, batch_key, document_version, cleaning_version, target_tokens, overlap_tokens, status, chunk_count, invalid_count, created_by, created_at)
        VALUES (:document_id, :batch_key, :document_version, :cleaning_version, :target_tokens, :overlap_tokens, :status, :chunk_count, :invalid_count, :created_by, :created_at)"""), {
        "document_id": document_id, "batch_key": batch_key, "document_version": document["version"], "cleaning_version": CLEANING_VERSION,
        "target_tokens": target_tokens, "overlap_tokens": overlap_tokens, "status": status, "chunk_count": len(chunks),
        "invalid_count": invalid_count, "created_by": user.user_id, "created_at": now,
    })
    batch_id = int(session.execute(text("SELECT LAST_INSERT_ID()")).scalar_one())
    for index, chunk in enumerate(chunks):
        issues = _validate_chunk(chunk, target_tokens)
        metadata = {
            "document_version": document["version"], "batch_key": batch_key, "cleaning_version": CLEANING_VERSION,
            "target_tokens": target_tokens, "overlap_tokens": overlap_tokens, "estimated_tokens": estimate_tokens(chunk["content"]),
            "validation_status": "INVALID" if issues else "VALID", "validation_issues": issues,
            "source_block_types": sorted({item["block_type"] for item in chunk["source_sections"]}),
        }
        chunk_key = f"{document['document_key']}/{batch_key}/chunk-{index:04d}"
        session.execute(text("""INSERT INTO rag_chunk
            (document_id, batch_id, chunk_key, chunk_index, heading_path, content, start_char, end_char, chroma_collection, chroma_id, embedding_model, metadata, created_at)
            VALUES (:document_id, :batch_id, :chunk_key, :chunk_index, :heading_path, :content, :start_char, :end_char, :chroma_collection, :chroma_id, :embedding_model, :metadata, :created_at)"""), {
            "document_id": document_id, "batch_id": batch_id, "chunk_key": chunk_key, "chunk_index": index,
            "heading_path": chunk.get("heading_path"), "content": chunk["content"], "start_char": chunk["start_char"], "end_char": chunk["end_char"],
            "chroma_collection": settings.chroma_collection, "chroma_id": chunk_key, "embedding_model": settings.embedding_model or "PENDING",
            "metadata": json.dumps(metadata, ensure_ascii=False), "created_at": now,
        })
    session.execute(text("UPDATE rag_document SET chunk_count=:chunk_count, vector_status='PENDING', updated_at=:updated_at WHERE id=:id"), {"chunk_count": len(chunks), "updated_at": now, "id": document_id})
    record_audit_event(session, action="RAG_CHUNK_BATCH_CREATED", resource_type="rag_chunk_batch", resource_id=str(batch_id), actor_user_id=user.user_id, after_state={"document_id": document_id, "status": status, "chunk_count": len(chunks), "invalid_count": invalid_count}, commit=True)
    return get_chunk_batch(session, document_id, batch_key=batch_key)  # type: ignore[return-value]
