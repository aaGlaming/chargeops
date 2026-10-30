"""OpenAI-compatible Embedding and Chroma indexing services."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings
from app.schemas.rag import (
    RagEmbeddingBatchListResponse,
    RagEmbeddingBatchResponse,
    RagEmbeddingBatchSummary,
    RagEmbeddingItemSummary,
)
from app.services.auth import UserContext, record_audit_event
from app.telemetry import record_sample


class EmbeddingServiceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _safe_model_key(model: str) -> str:
    return hashlib.sha1(model.encode("utf-8")).hexdigest()[:12]


def _embedding_values(settings: Settings) -> dict[str, Any]:
    if not settings.embedding_base_url or not settings.embedding_api_key or not settings.embedding_model:
        raise EmbeddingServiceError("EMBEDDING_NOT_CONFIGURED", "Embedding 服务配置不完整")
    return {
        "model": settings.embedding_model,
        "batch_size": settings.embedding_batch_size,
        "timeout_seconds": settings.embedding_timeout_seconds,
        "max_retries": settings.embedding_max_retries,
        "rate_limit_per_second": settings.embedding_rate_limit_per_second,
    }


def embed_texts(settings: Settings, values: list[str]) -> list[list[float]]:
    """Call an OpenAI-compatible /embeddings endpoint with bounded retries."""
    if not values:
        return []
    started = time.perf_counter()
    config = _embedding_values(settings)
    payload = {"model": config["model"], "input": values}
    headers = {"Authorization": f"Bearer {settings.embedding_api_key}", "Content-Type": "application/json"}
    last_error = "unknown embedding error"
    with httpx.Client(timeout=config["timeout_seconds"]) as client:
        for attempt in range(config["max_retries"] + 1):
            try:
                response = client.post(f"{settings.embedding_base_url}/embeddings", headers=headers, json=payload)
                response.raise_for_status()
                body = response.json()
                data = body.get("data")
                if not isinstance(data, list) or len(data) != len(values):
                    raise EmbeddingServiceError("EMBEDDING_RESPONSE_INVALID", "Embedding 返回数量与输入不一致")
                ordered = sorted(data, key=lambda item: item.get("index", 0))
                embeddings = [item.get("embedding") for item in ordered]
                if any(not isinstance(item, list) or not item for item in embeddings):
                    raise EmbeddingServiceError("EMBEDDING_RESPONSE_INVALID", "Embedding 返回向量为空")
                record_sample("embedding", (time.perf_counter() - started) * 1000, "success")
                return embeddings
            except EmbeddingServiceError:
                record_sample("embedding", (time.perf_counter() - started) * 1000, "error")
                raise
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                last_error = str(exc)[:1800]
                if attempt >= config["max_retries"]:
                    break
                time.sleep(min(2**attempt, 8))
    record_sample("embedding", (time.perf_counter() - started) * 1000, "error")
    raise EmbeddingServiceError("EMBEDDING_REQUEST_FAILED", last_error)


def _chroma_collection(settings: Settings) -> Any:
    return _ChromaCollection(settings)


class _ChromaCollection:
    """Small Chroma v2 HTTP adapter, independent of client-side config formats."""

    def __init__(self, settings: Settings) -> None:
        self.base_url = f"http://{settings.chroma_host}:{settings.chroma_port}/api/v2/tenants/default_tenant/databases/default_database"
        self.name = settings.chroma_collection
        self.timeout = settings.embedding_timeout_seconds
        self.collection_id = self._get_or_create_id()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            response = httpx.request(method, f"{self.base_url}{path}", timeout=self.timeout, **kwargs)
            response.raise_for_status()
            record_sample("chroma", (time.perf_counter() - started) * 1000, "success")
            return response.json() if response.content else None
        except httpx.HTTPError as exc:
            record_sample("chroma", (time.perf_counter() - started) * 1000, "error")
            raise EmbeddingServiceError("CHROMA_REQUEST_FAILED", str(exc)[:1800]) from exc

    def _get_or_create_id(self) -> str:
        collections = self._request("GET", "/collections", params={"limit": 1000, "offset": 0})
        for item in collections or []:
            if item.get("name") == self.name:
                return str(item["id"])
        # Chroma v2 rejects an empty metadata object on collection creation.
        # Keep a stable marker so both fresh and upgraded Chroma instances
        # accept the request.
        created = self._request("POST", "/collections", json={"name": self.name, "get_or_create": True, "metadata": {"owner": "chargeops"}})
        if not created or not created.get("id"):
            raise EmbeddingServiceError("CHROMA_COLLECTION_FAILED", "无法创建 Chroma collection")
        return str(created["id"])

    def upsert(self, *, ids: list[str], documents: list[str], metadatas: list[dict[str, Any]], embeddings: list[list[float]]) -> None:
        self._request("POST", f"/collections/{self.collection_id}/upsert", json={"ids": ids, "documents": documents, "metadatas": metadatas, "embeddings": embeddings})

    def delete(self, *, ids: list[str]) -> None:
        if ids:
            self._request("POST", f"/collections/{self.collection_id}/delete", json={"ids": ids})

    def query(self, *, query_embeddings: list[list[float]], n_results: int, where: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "query_embeddings": query_embeddings,
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            payload["where"] = where
        return self._request("POST", f"/collections/{self.collection_id}/query", json=payload)

def _batch_summary(row: Any) -> RagEmbeddingBatchSummary:
    params = json.loads(row["parameters"]) if isinstance(row.get("parameters"), str) else (row.get("parameters") or {})
    return RagEmbeddingBatchSummary(
        id=int(row["id"]), batch_key=row["batch_key"], document_id=int(row["document_id"]),
        chunk_batch_id=int(row["chunk_batch_id"]) if row.get("chunk_batch_id") is not None else None,
        document_version=row["document_version"], embedding_model=row["embedding_model"], model_version=row["model_version"],
        status=row["status"], requested_count=int(row["requested_count"] or 0), success_count=int(row["success_count"] or 0),
        failed_count=int(row["failed_count"] or 0), pending_retry_count=int(row["pending_retry_count"] or 0), parameters=params,
        error_message=row["error_message"], created_by=int(row["created_by"]) if row.get("created_by") is not None else None,
        started_at=row["started_at"], completed_at=row["completed_at"], created_at=row["created_at"],
    )


def _item_summary(row: Any) -> RagEmbeddingItemSummary:
    return RagEmbeddingItemSummary(
        id=int(row["id"]), chunk_id=int(row["chunk_id"]), chunk_key=row["chunk_key"], chroma_id=row["chroma_id"],
        status=row["status"], attempt_count=int(row["attempt_count"] or 0),
        vector_dimension=int(row["vector_dimension"]) if row.get("vector_dimension") is not None else None,
        error_code=row["error_code"], error_message=row["error_message"],
    )


def get_embedding_batch(session: Session, batch_id: int) -> RagEmbeddingBatchResponse | None:
    batch = session.execute(text("SELECT * FROM rag_embedding_batch WHERE id=:id"), {"id": batch_id}).mappings().one_or_none()
    if batch is None:
        return None
    items = session.execute(text("SELECT * FROM rag_embedding_item WHERE embedding_batch_id=:id ORDER BY id"), {"id": batch_id}).mappings().all()
    return RagEmbeddingBatchResponse(batch=_batch_summary(batch), items=[_item_summary(row) for row in items])


def list_embedding_batches(session: Session, document_id: int | None = None) -> RagEmbeddingBatchListResponse:
    params: dict[str, Any] = {}
    where = ""
    if document_id is not None:
        where = "WHERE document_id=:document_id"
        params["document_id"] = document_id
    rows = session.execute(text(f"SELECT * FROM rag_embedding_batch {where} ORDER BY id DESC"), params).mappings().all()
    return RagEmbeddingBatchListResponse(items=[_batch_summary(row) for row in rows])


def _select_source_batch(session: Session, document_id: int, chunk_batch_key: str | None) -> tuple[Any | None, list[Any]]:
    batch = None
    if chunk_batch_key:
        batch = session.execute(text("SELECT * FROM rag_chunk_batch WHERE document_id=:document_id AND batch_key=:batch_key"), {"document_id": document_id, "batch_key": chunk_batch_key}).mappings().one_or_none()
    else:
        batch = session.execute(text("SELECT * FROM rag_chunk_batch WHERE document_id=:document_id ORDER BY id DESC LIMIT 1"), {"document_id": document_id}).mappings().one_or_none()
    if batch is not None:
        chunks = session.execute(text("""SELECT c.id, c.document_id, c.chunk_key, c.content, c.chroma_id, c.chunk_index,
            d.document_key, d.title, d.doc_type, d.source_type, d.source_url, d.region_code, d.version, d.effective_date
            FROM rag_chunk c JOIN rag_document d ON d.id=c.document_id
            WHERE c.batch_id=:batch_id ORDER BY c.chunk_index"""), {"batch_id": batch["id"]}).mappings().all()
        return batch, chunks
    legacy = session.execute(text("""SELECT c.id, c.document_id, c.chunk_key, c.content, c.chroma_id, c.chunk_index,
        d.document_key, d.title, d.doc_type, d.source_type, d.source_url, d.region_code, d.version, d.effective_date
        FROM rag_chunk c JOIN rag_document d ON d.id=c.document_id
        WHERE c.document_id=:document_id AND c.batch_id IS NULL ORDER BY c.chunk_index"""), {"document_id": document_id}).mappings().all()
    return None, legacy


def _document(session: Session, document_id: int) -> Any | None:
    return session.execute(text("SELECT id, version, parse_status, vector_status FROM rag_document WHERE id=:id AND deleted_at IS NULL"), {"id": document_id}).mappings().one_or_none()


def _existing_batch(session: Session, batch_key: str) -> Any | None:
    return session.execute(text("SELECT id, status FROM rag_embedding_batch WHERE batch_key=:batch_key"), {"batch_key": batch_key}).mappings().one_or_none()


def _update_item_metadata(session: Session, chunk_id: int, *, batch_id: int, model: str, vector_dimension: int, status: str) -> None:
    row = session.execute(text("SELECT metadata FROM rag_chunk WHERE id=:id"), {"id": chunk_id}).mappings().one()
    metadata = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else (row["metadata"] or {})
    metadata.update({"embedding_batch_id": batch_id, "embedding_model": model, "vector_dimension": vector_dimension, "vector_status": status})
    session.execute(text("UPDATE rag_chunk SET embedding_model=:model, metadata=:metadata WHERE id=:id"), {"model": model, "metadata": json.dumps(metadata, ensure_ascii=False), "id": chunk_id})


def _mark_batch_failure(session: Session, batch_id: int, error_code: str, message: str) -> None:
    now = _now()
    session.execute(text("""UPDATE rag_embedding_item SET status='FAILED', error_code=:error_code, error_message=:message, updated_at=:updated_at
        WHERE embedding_batch_id=:batch_id AND status='PENDING'"""), {"batch_id": batch_id, "error_code": error_code, "message": message[:2000], "updated_at": now})
    session.execute(text("""UPDATE rag_embedding_batch SET status='FAILED', failed_count=(SELECT COUNT(*) FROM rag_embedding_item WHERE embedding_batch_id=:batch_id AND status='FAILED'),
        pending_retry_count=(SELECT COUNT(*) FROM rag_embedding_item WHERE embedding_batch_id=:batch_id AND status='FAILED'), error_message=:message, completed_at=:completed_at WHERE id=:batch_id"""), {"batch_id": batch_id, "message": message[:2000], "completed_at": now})
    session.commit()


def delete_document_vectors(settings: Settings, chunk_ids: list[str]) -> None:
    if not chunk_ids:
        return
    collection = _chroma_collection(settings)
    try:
        collection.delete(ids=chunk_ids)
    except Exception as exc:
        raise EmbeddingServiceError("CHROMA_DELETE_FAILED", str(exc)[:1800]) from exc


def create_embedding_batch(
    session: Session,
    settings: Settings,
    user: UserContext,
    document_id: int,
    *,
    chunk_batch_key: str | None = None,
    force: bool = False,
    delete_existing: bool = False,
) -> RagEmbeddingBatchResponse:
    document = _document(session, document_id)
    if document is None:
        raise LookupError("document not found")
    if document["parse_status"] != "PARSED":
        raise ValueError("document must be PARSED before embedding")
    source_batch, chunks = _select_source_batch(session, document_id, chunk_batch_key)
    if chunk_batch_key and source_batch is None:
        raise LookupError("chunk batch not found")
    if not chunks:
        raise ValueError("document has no chunks to embed")
    config_error: EmbeddingServiceError | None = None
    try:
        config = _embedding_values(settings)
    except EmbeddingServiceError as exc:
        config_error = exc
        config = {
            "model": settings.embedding_model or "UNCONFIGURED",
            "batch_size": settings.embedding_batch_size,
            "timeout_seconds": settings.embedding_timeout_seconds,
            "max_retries": settings.embedding_max_retries,
            "rate_limit_per_second": settings.embedding_rate_limit_per_second,
        }
    source_id = int(source_batch["id"]) if source_batch is not None else 0
    model_name = str(config["model"])
    base_key = f"embed-{document_id}-{source_id}-{_safe_model_key(model_name)}"
    batch_key = f"{base_key}-{_now().strftime('%Y%m%d%H%M%S%f')}" if force else base_key
    existing = _existing_batch(session, batch_key)
    if existing is not None and not force:
        return get_embedding_batch(session, int(existing["id"]))  # type: ignore[return-value]

    now = _now()
    parameters = {**config, "chunk_batch_key": chunk_batch_key, "delete_existing": delete_existing, "operation": "rebuild" if delete_existing else "upsert"}
    session.execute(text("""INSERT INTO rag_embedding_batch
        (batch_key, document_id, chunk_batch_id, document_version, embedding_model, model_version, parameters, status, requested_count, created_by, started_at, created_at)
        VALUES (:batch_key, :document_id, :chunk_batch_id, :document_version, :embedding_model, :model_version, :parameters, 'RUNNING', :requested_count, :created_by, :started_at, :created_at)"""), {
        "batch_key": batch_key, "document_id": document_id, "chunk_batch_id": source_id or None, "document_version": document["version"],
        "embedding_model": model_name, "model_version": model_name, "parameters": json.dumps(parameters, ensure_ascii=False),
        "requested_count": len(chunks), "created_by": user.user_id, "started_at": now, "created_at": now,
    })
    batch_id = int(session.execute(text("SELECT LAST_INSERT_ID()")).scalar_one())
    for chunk in chunks:
        session.execute(text("""INSERT INTO rag_embedding_item
            (embedding_batch_id, chunk_id, chunk_key, chroma_id, status, created_at, updated_at)
            VALUES (:embedding_batch_id, :chunk_id, :chunk_key, :chroma_id, 'PENDING', :created_at, :updated_at)"""), {
            "embedding_batch_id": batch_id, "chunk_id": chunk["id"], "chunk_key": chunk["chunk_key"], "chroma_id": chunk["chroma_id"], "created_at": now, "updated_at": now,
        })
    session.commit()

    try:
        if config_error is not None:
            raise config_error
        collection = _chroma_collection(settings)
        if delete_existing:
            existing_ids = [row["chroma_id"] for row in session.execute(text("SELECT chroma_id FROM rag_chunk WHERE document_id=:document_id"), {"document_id": document_id}).mappings().all()]
            delete_document_vectors(settings, existing_ids)
        for offset in range(0, len(chunks), settings.embedding_batch_size):
            group = chunks[offset : offset + settings.embedding_batch_size]
            item_ids = [int(item["id"]) for item in group]
            for item_id in item_ids:
                session.execute(text("UPDATE rag_embedding_item SET attempt_count=attempt_count+1, updated_at=:updated_at WHERE embedding_batch_id=:batch_id AND chunk_id=:chunk_id"), {"batch_id": batch_id, "chunk_id": item_id, "updated_at": _now()})
            session.commit()
            if settings.embedding_rate_limit_per_second:
                time.sleep(1 / settings.embedding_rate_limit_per_second)
            try:
                vectors = embed_texts(settings, [item["content"] for item in group])
                metadata = [{
                    "chunk_id": item["chunk_key"], "document_id": int(item["document_id"]), "document_key": item["document_key"],
                    "title": item["title"], "doc_type": item["doc_type"], "source_type": item["source_type"],
                    "source_url": item["source_url"] or "", "region_code": item["region_code"] or "", "version": item["version"],
                    "effective_date": item["effective_date"].isoformat() if item.get("effective_date") else "",
                    "chunk_index": int(item["chunk_index"]), "start_char": int(item.get("start_char") or 0), "end_char": int(item.get("end_char") or 0),
                    "embedding_model": model_name, "embedding_batch_id": batch_id,
                } for item in group]
                collection.upsert(ids=[item["chroma_id"] for item in group], documents=[item["content"] for item in group], metadatas=metadata, embeddings=vectors)
                dimension = len(vectors[0])
                for item in group:
                    session.execute(text("UPDATE rag_embedding_item SET status='INDEXED', vector_dimension=:dimension, updated_at=:updated_at WHERE embedding_batch_id=:batch_id AND chunk_id=:chunk_id"), {"dimension": dimension, "updated_at": _now(), "batch_id": batch_id, "chunk_id": item["id"]})
                    _update_item_metadata(session, int(item["id"]), batch_id=batch_id, model=model_name, vector_dimension=dimension, status="INDEXED")
                session.commit()
            except Exception as exc:
                message = str(exc)[:2000]
                try:
                    collection.delete(ids=[item["chroma_id"] for item in group])
                except Exception:
                    pass
                for item_id in item_ids:
                    session.execute(text("""UPDATE rag_embedding_item SET status='FAILED', error_code='EMBEDDING_OR_CHROMA_FAILED', error_message=:message, updated_at=:updated_at
                        WHERE embedding_batch_id=:batch_id AND chunk_id=:chunk_id"""), {"message": message, "updated_at": _now(), "batch_id": batch_id, "chunk_id": item_id})
                session.commit()
        counts = session.execute(text("SELECT SUM(status='INDEXED') AS success_count, SUM(status='FAILED') AS failed_count FROM rag_embedding_item WHERE embedding_batch_id=:batch_id"), {"batch_id": batch_id}).mappings().one()
        success_count, failed_count = int(counts["success_count"] or 0), int(counts["failed_count"] or 0)
        final_status = "COMPLETED" if failed_count == 0 else ("PARTIAL" if success_count else "FAILED")
        error_message = None if failed_count == 0 else "部分 Chunk 向量化失败，可通过重试接口再次执行"
        session.execute(text("""UPDATE rag_embedding_batch SET status=:status, success_count=:success_count, failed_count=:failed_count,
            pending_retry_count=:failed_count, error_message=:error_message, completed_at=:completed_at WHERE id=:batch_id"""), {"status": final_status, "success_count": success_count, "failed_count": failed_count, "error_message": error_message, "completed_at": _now(), "batch_id": batch_id})
        document_status = "INDEXED" if success_count == len(chunks) else ("PARTIAL" if success_count else "FAILED")
        session.execute(text("UPDATE rag_document SET vector_status=:vector_status, embedding_model=:embedding_model, updated_at=:updated_at WHERE id=:id"), {"vector_status": document_status, "embedding_model": model_name, "updated_at": _now(), "id": document_id})
        record_audit_event(session, action="RAG_EMBEDDING_BATCH_COMPLETED", resource_type="rag_embedding_batch", resource_id=str(batch_id), actor_user_id=user.user_id, after_state={"document_id": document_id, "status": final_status, "success_count": success_count, "failed_count": failed_count}, commit=True)
    except EmbeddingServiceError as exc:
        session.rollback()
        _mark_batch_failure(session, batch_id, exc.code, exc.message)
        session.execute(text("UPDATE rag_document SET vector_status='FAILED', updated_at=:updated_at WHERE id=:id"), {"updated_at": _now(), "id": document_id})
        session.commit()
    except Exception as exc:
        session.rollback()
        _mark_batch_failure(session, batch_id, "EMBEDDING_BATCH_FAILED", str(exc))
        session.execute(text("UPDATE rag_document SET vector_status='FAILED', updated_at=:updated_at WHERE id=:id"), {"updated_at": _now(), "id": document_id})
        session.commit()
    result = get_embedding_batch(session, batch_id)
    if result is None:
        raise EmbeddingServiceError("EMBEDDING_BATCH_NOT_FOUND", "向量化批次保存失败")
    return result
