"""Hybrid RAG retrieval, filtering, ranking and original-fragment hydration."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT, Settings
from app.schemas.rag import RagSearchHit, RagSearchRequest, RagSearchResponse
from app.services.auth import UserContext, record_audit_event
from app.services.rag_embeddings import EmbeddingServiceError, _chroma_collection, embed_texts


TOKEN_PATTERN = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)
REWRITE_ALIASES = {"充电桩": "充电站", "快充": "直流快充", "慢充": "交流慢充"}


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def rewrite_query(query: str) -> tuple[str, dict[str, object]]:
    value = " ".join("".join(char for char in query if char in {"\n", "\t"} or ord(char) >= 32).split())
    rules: list[str] = []
    for source, target in REWRITE_ALIASES.items():
        if source in value:
            value = value.replace(source, target)
            rules.append(f"{source}->{target}")
    return value, {"normalized": value != query, "rules": rules, "method": "deterministic_alias_normalization"}


def _terms(query: str) -> list[str]:
    values = TOKEN_PATTERN.findall(query.lower())
    return list(dict.fromkeys(value for value in values if len(value) > 1))[:20]


def _where_filter(request: RagSearchRequest) -> dict[str, Any] | None:
    conditions: list[dict[str, Any]] = []
    for key, value in (("doc_type", request.doc_type), ("region_code", request.region_code), ("version", request.version)):
        if value:
            conditions.append({key: {"$eq": value}})
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions} if conditions else None


def _effective_date_ok(value: Any, request: RagSearchRequest) -> bool:
    if request.effective_date_from is None and request.effective_date_to is None:
        return True
    if value in {None, ""}:
        return False
    try:
        current = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    except ValueError:
        return False
    if request.effective_date_from and current < request.effective_date_from:
        return False
    if request.effective_date_to and current > request.effective_date_to:
        return False
    return True


def _vector_candidates(settings: Settings, query: str, request: RagSearchRequest) -> list[dict[str, Any]]:
    vector = embed_texts(settings, [query])[0]
    collection = _chroma_collection(settings)
    result = collection.query(query_embeddings=[vector], n_results=max(request.top_k * 3, request.top_k), where=_where_filter(request))
    ids = (result.get("ids") or [[]])[0] or []
    distances = (result.get("distances") or [[]])[0] or []
    metadatas = (result.get("metadatas") or [[]])[0] or []
    documents = (result.get("documents") or [[]])[0] or []
    candidates: list[dict[str, Any]] = []
    for index, chunk_id in enumerate(ids):
        metadata = metadatas[index] if index < len(metadatas) else {}
        if not isinstance(metadata, dict) or (metadata.get("effective_date") and not _effective_date_ok(metadata.get("effective_date"), request)):
            continue
        distance = float(distances[index]) if index < len(distances) and distances[index] is not None else 1.0
        candidates.append({"chunk_key": chunk_id, "vector_score": 1.0 / (1.0 + max(distance, 0.0)), "metadata": metadata, "content": documents[index] if index < len(documents) and documents[index] else ""})
    return candidates


def _keyword_candidates(session: Session, query: str, request: RagSearchRequest) -> list[dict[str, Any]]:
    terms = _terms(query)
    if not terms:
        return []
    conditions = ["d.deleted_at IS NULL", "d.parse_status='PARSED'"]
    params: dict[str, Any] = {}
    if request.doc_type:
        conditions.append("d.doc_type=:doc_type")
        params["doc_type"] = request.doc_type
    if request.region_code:
        conditions.append("d.region_code=:region_code")
        params["region_code"] = request.region_code
    if request.version:
        conditions.append("d.version=:version")
        params["version"] = request.version
    if request.effective_date_from:
        conditions.append("d.effective_date>=:effective_date_from")
        params["effective_date_from"] = request.effective_date_from
    if request.effective_date_to:
        conditions.append("d.effective_date<=:effective_date_to")
        params["effective_date_to"] = request.effective_date_to
    term_conditions = []
    for index, term in enumerate(terms):
        key = f"term_{index}"
        term_conditions.append(f"(c.content LIKE :{key} OR d.title LIKE :{key})")
        params[key] = f"%{term}%"
    conditions.append("(" + " OR ".join(term_conditions) + ")")
    rows = session.execute(text(f"""SELECT c.id, c.document_id, c.chunk_key, c.content, c.chunk_index, c.start_char, c.end_char,
        c.heading_path, c.metadata, d.title, d.doc_type, d.source_type, d.source_url, d.region_code, d.version,
        d.effective_date, d.original_file
        FROM rag_chunk c JOIN rag_document d ON d.id=c.document_id
        WHERE {' AND '.join(conditions)} ORDER BY d.updated_at DESC, c.chunk_index LIMIT :limit"""), {**params, "limit": max(request.top_k * 5, 50)}).mappings().all()
    result: list[dict[str, Any]] = []
    for row in rows:
        haystack = f"{row['content']} {row['title']}".lower()
        matched = sum(1 for term in terms if term in haystack)
        result.append({"chunk_key": row["chunk_key"], "keyword_score": matched / len(terms), "row": row})
    return result


def _load_rows(session: Session, keys: set[str]) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for key in keys:
        row = session.execute(text("""SELECT c.id, c.document_id, c.chunk_key, c.content, c.chunk_index, c.start_char, c.end_char,
            c.heading_path, c.metadata, d.title, d.doc_type, d.source_type, d.source_url, d.region_code, d.version,
            d.effective_date, d.original_file
            FROM rag_chunk c JOIN rag_document d ON d.id=c.document_id WHERE c.chunk_key=:chunk_key AND d.deleted_at IS NULL"""), {"chunk_key": key}).mappings().one_or_none()
        if row is not None:
            rows[key] = row
    return rows


def _original_fragment(row: Any) -> str:
    path = PROJECT_ROOT / Path(row["original_file"])
    if not path.exists():
        return row["content"]
    try:
        content = path.read_text(encoding="utf-8-sig")
        start = max(0, min(int(row["start_char"]), len(content)))
        end = max(start, min(int(row["end_char"]), len(content)))
        return content[start:end] or row["content"]
    except (OSError, UnicodeError):
        return row["content"]


def _metadata(row: Any) -> dict[str, object]:
    value = row["metadata"]
    return json.loads(value) if isinstance(value, str) else (value or {})


def _scenario_ok(row: Any, request: RagSearchRequest) -> bool:
    if not request.agent_scenario:
        return True
    metadata = _metadata(row)
    labels = metadata.get("agent_scenarios") or metadata.get("agent_scenario")
    if isinstance(labels, str):
        labels = [labels]
    return request.agent_scenario in (labels or [])


def _rerank_score(content: str, query: str, base_score: float) -> float:
    normalized_content = content.lower()
    normalized_query = query.lower()
    if normalized_query and normalized_query in normalized_content:
        return min(1.0, base_score + 0.12)
    terms = _terms(query)
    coverage = sum(1 for term in terms if term in normalized_content) / max(1, len(terms))
    return min(1.0, base_score + coverage * 0.05)


def search_rag(session: Session, settings: Settings, user: UserContext, request: RagSearchRequest) -> RagSearchResponse:
    rewritten_query, rewrite_info = rewrite_query(request.query)
    run_id = str(uuid4())
    vector_candidates: list[dict[str, Any]] = []
    keyword_candidates: list[dict[str, Any]] = []
    warnings: list[str] = []
    if request.use_vector:
        try:
            vector_candidates = _vector_candidates(settings, rewritten_query, request)
        except EmbeddingServiceError as exc:
            warnings.append(f"{exc.code}: {exc.message}")
    if request.use_keyword:
        keyword_candidates = _keyword_candidates(session, rewritten_query, request)

    vector_map = {item["chunk_key"]: item for item in vector_candidates}
    keyword_map = {item["chunk_key"]: item for item in keyword_candidates}
    rows = _load_rows(session, set(vector_map) | set(keyword_map))
    hits: list[RagSearchHit] = []
    for key in set(vector_map) | set(keyword_map):
        row = rows.get(key)
        if row is None:
            continue
        if not _effective_date_ok(row["effective_date"], request):
            continue
        if not _scenario_ok(row, request):
            continue
        vector_score = vector_map.get(key, {}).get("vector_score")
        keyword_score = keyword_map.get(key, {}).get("keyword_score")
        if vector_score is not None and keyword_score is not None:
            score = 0.7 * float(vector_score) + 0.3 * float(keyword_score)
        else:
            score = float(vector_score if vector_score is not None else keyword_score or 0.0)
        rerank_score = _rerank_score(row["content"], rewritten_query, score) if request.use_rerank else None
        final_score = rerank_score if rerank_score is not None else score
        hit_metadata = _metadata(row)
        hits.append(RagSearchHit(
            chunk_id=row["chunk_key"], document_id=int(row["document_id"]), title=row["title"], doc_type=row["doc_type"],
            source_type=row["source_type"], source_url=row["source_url"], region_code=row["region_code"], version=row["version"],
            effective_date=row["effective_date"], chunk_index=int(row["chunk_index"]), start_char=int(row["start_char"]), end_char=int(row["end_char"]),
            content=row["content"], original_fragment=_original_fragment(row),
            original_href=f"/rag/documents/{int(row['document_id'])}/source?start_char={int(row['start_char'])}&end_char={int(row['end_char'])}",
            vector_score=vector_score, keyword_score=keyword_score, rerank_score=rerank_score, score=final_score,
            match_sources=[source for source, present in (("vector", vector_score is not None), ("keyword", keyword_score is not None)) if present],
            metadata=hit_metadata,
        ))
    hits.sort(key=lambda item: (-item.score, item.chunk_id))
    hits = hits[: request.top_k]
    if not hits:
        status = "NO_HIT"
    elif hits[0].score < 0.2:
        status = "EVIDENCE_INSUFFICIENT"
    else:
        status = "HIT"

    filters = request.model_dump(mode="json", exclude={"query", "top_k", "use_vector", "use_keyword", "use_rerank"})
    filters["agent_scenario"] = request.agent_scenario
    filters["warnings"] = warnings
    now = _now()
    session.execute(text("""INSERT INTO rag_search_log
        (run_id, query_text, rewritten_query, agent_scenario, filters, vector_count, keyword_count, hit_count, hit_chunk_ids, status, actor_user_id, created_at)
        VALUES (:run_id, :query_text, :rewritten_query, :agent_scenario, :filters, :vector_count, :keyword_count, :hit_count, :hit_chunk_ids, :status, :actor_user_id, :created_at)"""), {
        "run_id": run_id, "query_text": request.query, "rewritten_query": rewritten_query, "agent_scenario": request.agent_scenario,
        "filters": json.dumps(filters, ensure_ascii=False, default=str), "vector_count": len(vector_candidates), "keyword_count": len(keyword_candidates),
        "hit_count": len(hits), "hit_chunk_ids": json.dumps([hit.chunk_id for hit in hits], ensure_ascii=False), "status": status,
        "actor_user_id": user.user_id, "created_at": now,
    })
    record_audit_event(session, action="RAG_SEARCH", resource_type="rag_search", resource_id=run_id, actor_user_id=user.user_id, after_state={"status": status, "hit_count": len(hits)}, metadata={"query": request.query, "filters": filters}, commit=True)
    return RagSearchResponse(
        run_id=run_id, query=request.query, rewritten_query=rewritten_query, query_rewrite=rewrite_info, filters=filters,
        top_k=request.top_k, status=status, vector_count=len(vector_candidates), keyword_count=len(keyword_candidates),
        rerank_applied=request.use_rerank, warnings=warnings, hits=hits, created_at=now,
    )
