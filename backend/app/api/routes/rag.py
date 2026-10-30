from __future__ import annotations

import time
from datetime import date
from typing import Literal

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user
from app.config import Settings, get_settings
from app.db import get_db
from app.errors import AppError
from app.config import PROJECT_ROOT
from app.schemas.rag import (
    RagChunkBatchListResponse,
    RagChunkBatchResponse,
    RagChunkRequest,
    RagDocumentDetail,
    RagDocumentListResponse,
    RagEmbeddingBatchListResponse,
    RagEmbeddingBatchResponse,
    RagEmbeddingRequest,
    RagOriginalFragment,
    RagSearchRequest,
    RagSearchResponse,
    RagUploadResponse,
)
from app.services.auth import UserContext, require_permission
from app.services.rag_chunks import create_chunk_batch, get_chunk_batch, list_chunk_batches
from app.services.rag_documents import get_document, list_documents, retry_document, upload_document
from app.services.rag_embeddings import (
    EmbeddingServiceError,
    create_embedding_batch,
    delete_document_vectors,
    get_embedding_batch,
    list_embedding_batches,
)
from app.services.rag_search import search_rag
from app.telemetry import record_sample


router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/search", response_model=RagSearchResponse, summary="Hybrid RAG search with original fragments")
def rag_search(request: RagSearchRequest, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> RagSearchResponse:
    require_permission(user, "rag.read", session=session)
    started = time.perf_counter()
    try:
        result = search_rag(session, settings, user, request)
        record_sample("rag_search", (time.perf_counter() - started) * 1000, "success")
        return result
    except EmbeddingServiceError as exc:
        record_sample("rag_search", (time.perf_counter() - started) * 1000, "error")
        raise AppError(exc.code, exc.message, status_code=502) from exc


@router.post("/documents", response_model=RagUploadResponse, status_code=status.HTTP_201_CREATED, summary="Upload and parse a Markdown document")
async def upload_rag_document(
    response: Response,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    doc_type: str = Form(default="business_rule"),
    source_type: Literal["public", "user_upload", "synthetic", "agent"] = Form(default="user_upload"),
    source_url: str | None = Form(default=None),
    region_code: str | None = Form(default=None),
    version: str = Form(default="latest"),
    effective_date: date | None = Form(default=None),
    document_key: str | None = Form(default=None),
    user: UserContext = Depends(get_current_user),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RagUploadResponse:
    require_permission(user, "rag.write", session=session)
    if file.content_type not in {None, "text/markdown", "text/plain", "application/octet-stream"}:
        raise AppError("INVALID_RAG_CONTENT_TYPE", "仅支持 Markdown 文本文件", status_code=400)
    try:
        content = await file.read(settings.rag_max_file_size_bytes + 1)
        document, duplicate, message = upload_document(
            session, settings, user, filename=file.filename or "", content=content, title=title,
            doc_type=doc_type, source_type=source_type, source_url=source_url, region_code=region_code,
            version=version, effective_date=effective_date, document_key=document_key,
        )
    except ValueError as exc:
        raise AppError("INVALID_RAG_DOCUMENT", str(exc), status_code=400) from exc
    except IntegrityError as exc:
        session.rollback()
        raise AppError("RAG_DOCUMENT_CONFLICT", "文档键或文档元数据已存在", status_code=409) from exc
    if duplicate:
        response.status_code = status.HTTP_200_OK
    return RagUploadResponse(document=document, duplicate=duplicate, message=message)


@router.get("/documents", response_model=RagDocumentListResponse, summary="List RAG documents")
def rag_documents(
    doc_type: str | None = None,
    parse_status: str | None = None,
    vector_status: str | None = None,
    region_code: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    user: UserContext = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> RagDocumentListResponse:
    require_permission(user, "rag.read", session=session)
    items, total = list_documents(session, doc_type=doc_type, parse_status=parse_status, vector_status=vector_status, region_code=region_code, page=page, page_size=page_size)
    return RagDocumentListResponse(items=items, page={"page": page, "page_size": page_size, "total": total, "has_next": page * page_size < total})


@router.get("/documents/{document_id}", response_model=RagDocumentDetail, summary="Get RAG document detail")
def rag_document_detail(document_id: int, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> RagDocumentDetail:
    require_permission(user, "rag.read", session=session)
    document = get_document(session, document_id)
    if document is None:
        raise AppError("RAG_DOCUMENT_NOT_FOUND", "RAG 文档不存在", status_code=404, details={"document_id": document_id})
    return document


@router.get("/documents/{document_id}/source", response_model=RagOriginalFragment, summary="Read an original Markdown fragment")
def rag_document_source(
    document_id: int,
    start_char: int = Query(default=0, ge=0),
    end_char: int | None = Query(default=None, ge=1),
    user: UserContext = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> RagOriginalFragment:
    require_permission(user, "rag.read", session=session)
    row = session.execute(text("SELECT original_file FROM rag_document WHERE id=:id AND deleted_at IS NULL"), {"id": document_id}).mappings().one_or_none()
    if row is None:
        raise AppError("RAG_DOCUMENT_NOT_FOUND", "RAG 文档不存在", status_code=404, details={"document_id": document_id})
    path = PROJECT_ROOT / Path(row["original_file"])
    if not path.exists():
        raise AppError("RAG_DOCUMENT_SOURCE_MISSING", "RAG 原文文件不存在", status_code=404, details={"document_id": document_id})
    content = path.read_text(encoding="utf-8-sig")
    bounded_end = min(len(content), end_char if end_char is not None else len(content))
    if bounded_end < start_char:
        raise AppError("INVALID_RAG_SOURCE_RANGE", "原文字符范围无效", status_code=400)
    return RagOriginalFragment(document_id=document_id, start_char=start_char, end_char=bounded_end, content=content[start_char:bounded_end])


@router.get("/documents/{document_id}/chunks/batches", response_model=RagChunkBatchListResponse, summary="List historical chunk batches")
def rag_chunk_batches(document_id: int, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> RagChunkBatchListResponse:
    require_permission(user, "rag.read", session=session)
    if get_document(session, document_id, include_sections=False) is None:
        raise AppError("RAG_DOCUMENT_NOT_FOUND", "RAG 文档不存在", status_code=404, details={"document_id": document_id})
    return list_chunk_batches(session, document_id)


@router.get("/documents/{document_id}/chunks/preview", response_model=RagChunkBatchResponse, summary="Preview a chunk batch")
def rag_chunk_preview(document_id: int, batch_key: str | None = Query(default=None), user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> RagChunkBatchResponse:
    require_permission(user, "rag.read", session=session)
    result = get_chunk_batch(session, document_id, batch_key=batch_key)
    if result is None:
        raise AppError("RAG_CHUNK_BATCH_NOT_FOUND", "Chunk 批次不存在", status_code=404, details={"document_id": document_id, "batch_key": batch_key})
    return result


@router.post("/documents/{document_id}/chunks/preview", response_model=RagChunkBatchResponse, summary="Clean and preview Markdown chunks")
def preview_rag_chunks(document_id: int, request: RagChunkRequest, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> RagChunkBatchResponse:
    require_permission(user, "rag.write", session=session)
    try:
        return create_chunk_batch(session, settings, user, document_id, target_tokens=request.target_tokens, overlap_tokens=request.overlap_tokens, status="PREVIEW")
    except LookupError as exc:
        raise AppError("RAG_DOCUMENT_NOT_FOUND", "RAG 文档不存在", status_code=404, details={"document_id": document_id}) from exc
    except ValueError as exc:
        raise AppError("INVALID_RAG_CHUNK_REQUEST", str(exc), status_code=400) from exc


@router.post("/documents/{document_id}/chunks/rebuild", response_model=RagChunkBatchResponse, summary="Rebuild and retain a new chunk batch")
def rebuild_rag_chunks(document_id: int, request: RagChunkRequest, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> RagChunkBatchResponse:
    require_permission(user, "rag.write", session=session)
    try:
        return create_chunk_batch(session, settings, user, document_id, target_tokens=request.target_tokens, overlap_tokens=request.overlap_tokens, status="GENERATED")
    except LookupError as exc:
        raise AppError("RAG_DOCUMENT_NOT_FOUND", "RAG 文档不存在", status_code=404, details={"document_id": document_id}) from exc
    except ValueError as exc:
        raise AppError("INVALID_RAG_CHUNK_REQUEST", str(exc), status_code=400) from exc


@router.get("/embedding-batches", response_model=RagEmbeddingBatchListResponse, summary="List Embedding batches")
def rag_embedding_batches(document_id: int | None = Query(default=None), user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> RagEmbeddingBatchListResponse:
    require_permission(user, "rag.read", session=session)
    return list_embedding_batches(session, document_id=document_id)


@router.get("/embedding-batches/{batch_id}", response_model=RagEmbeddingBatchResponse, summary="Get an Embedding batch")
def rag_embedding_batch_detail(batch_id: int, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> RagEmbeddingBatchResponse:
    require_permission(user, "rag.read", session=session)
    result = get_embedding_batch(session, batch_id)
    if result is None:
        raise AppError("RAG_EMBEDDING_BATCH_NOT_FOUND", "Embedding 批次不存在", status_code=404, details={"batch_id": batch_id})
    return result


@router.post("/documents/{document_id}/embeddings", response_model=RagEmbeddingBatchResponse, summary="Embed and index one document")
def embed_rag_document(document_id: int, request: RagEmbeddingRequest, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> RagEmbeddingBatchResponse:
    require_permission(user, "rag.write", session=session)
    try:
        return create_embedding_batch(session, settings, user, document_id, chunk_batch_key=request.chunk_batch_key, force=request.force)
    except LookupError as exc:
        raise AppError("RAG_DOCUMENT_OR_CHUNK_BATCH_NOT_FOUND", "文档或 Chunk 批次不存在", status_code=404, details={"document_id": document_id}) from exc
    except ValueError as exc:
        raise AppError("INVALID_RAG_EMBEDDING_REQUEST", str(exc), status_code=400) from exc
    except EmbeddingServiceError as exc:
        raise AppError(exc.code, exc.message, status_code=502) from exc


@router.post("/chunk-batches/{chunk_batch_key}/embeddings", response_model=RagEmbeddingBatchResponse, summary="Embed one Chunk batch")
def embed_rag_chunk_batch(chunk_batch_key: str, request: RagEmbeddingRequest, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> RagEmbeddingBatchResponse:
    require_permission(user, "rag.write", session=session)
    row = session.execute(text("SELECT document_id FROM rag_chunk_batch WHERE batch_key=:batch_key"), {"batch_key": chunk_batch_key}).mappings().one_or_none()
    if row is None:
        raise AppError("RAG_CHUNK_BATCH_NOT_FOUND", "Chunk 批次不存在", status_code=404, details={"batch_key": chunk_batch_key})
    try:
        return create_embedding_batch(session, settings, user, int(row["document_id"]), chunk_batch_key=chunk_batch_key, force=request.force)
    except ValueError as exc:
        raise AppError("INVALID_RAG_EMBEDDING_REQUEST", str(exc), status_code=400) from exc
    except EmbeddingServiceError as exc:
        raise AppError(exc.code, exc.message, status_code=502) from exc


@router.post("/documents/{document_id}/embeddings/rebuild", response_model=RagEmbeddingBatchResponse, summary="Delete and rebuild document vectors")
def rebuild_rag_document_embeddings(document_id: int, request: RagEmbeddingRequest, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> RagEmbeddingBatchResponse:
    require_permission(user, "rag.write", session=session)
    try:
        return create_embedding_batch(session, settings, user, document_id, chunk_batch_key=request.chunk_batch_key, force=True, delete_existing=True)
    except LookupError as exc:
        raise AppError("RAG_DOCUMENT_OR_CHUNK_BATCH_NOT_FOUND", "文档或 Chunk 批次不存在", status_code=404, details={"document_id": document_id}) from exc
    except ValueError as exc:
        raise AppError("INVALID_RAG_EMBEDDING_REQUEST", str(exc), status_code=400) from exc
    except EmbeddingServiceError as exc:
        raise AppError(exc.code, exc.message, status_code=502) from exc


@router.post("/embedding-batches/{batch_id}/retry", response_model=RagEmbeddingBatchResponse, summary="Retry failed Embedding items")
def retry_rag_embedding_batch(batch_id: int, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> RagEmbeddingBatchResponse:
    require_permission(user, "rag.write", session=session)
    row = session.execute(text("""SELECT b.document_id, c.batch_key FROM rag_embedding_batch b
        LEFT JOIN rag_chunk_batch c ON c.id=b.chunk_batch_id WHERE b.id=:id"""), {"id": batch_id}).mappings().one_or_none()
    if row is None:
        raise AppError("RAG_EMBEDDING_BATCH_NOT_FOUND", "Embedding 批次不存在", status_code=404, details={"batch_id": batch_id})
    try:
        return create_embedding_batch(session, settings, user, int(row["document_id"]), chunk_batch_key=row["batch_key"], force=True)
    except (LookupError, ValueError) as exc:
        raise AppError("INVALID_RAG_EMBEDDING_RETRY", str(exc), status_code=400) from exc
    except EmbeddingServiceError as exc:
        raise AppError(exc.code, exc.message, status_code=502) from exc


@router.delete("/documents/{document_id}/embeddings", summary="Delete document vectors")
def delete_rag_document_embeddings(document_id: int, version: str | None = Query(default=None), user: UserContext = Depends(get_current_user), session: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict[str, object]:
    require_permission(user, "rag.write", session=session)
    document = session.execute(text("SELECT id, version FROM rag_document WHERE id=:id AND deleted_at IS NULL"), {"id": document_id}).mappings().one_or_none()
    if document is None:
        raise AppError("RAG_DOCUMENT_NOT_FOUND", "RAG 文档不存在", status_code=404, details={"document_id": document_id})
    if version is not None and version != document["version"]:
        raise AppError("RAG_DOCUMENT_VERSION_NOT_FOUND", "文档版本不匹配", status_code=404, details={"document_id": document_id, "version": version})
    ids = [row["chroma_id"] for row in session.execute(text("SELECT chroma_id FROM rag_chunk WHERE document_id=:document_id"), {"document_id": document_id}).mappings().all()]
    try:
        delete_document_vectors(settings, ids)
    except EmbeddingServiceError as exc:
        raise AppError(exc.code, exc.message, status_code=502) from exc
    session.execute(text("""UPDATE rag_chunk
        SET embedding_model='PENDING', metadata=JSON_SET(COALESCE(metadata, JSON_OBJECT()), '$.vector_status', 'PENDING')
        WHERE document_id=:document_id"""), {"document_id": document_id})
    session.execute(text("UPDATE rag_document SET vector_status='PENDING', updated_at=NOW() WHERE id=:id"), {"id": document_id})
    session.commit()
    return {"document_id": document_id, "version": document["version"], "deleted_count": len(ids), "vector_status": "PENDING"}


@router.post("/documents/{document_id}/retry", response_model=RagDocumentDetail, summary="Retry Markdown parsing")
def retry_rag_document(document_id: int, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> RagDocumentDetail:
    require_permission(user, "rag.write", session=session)
    try:
        return retry_document(session, settings, document_id, user)
    except LookupError as exc:
        raise AppError("RAG_DOCUMENT_NOT_FOUND", "RAG 文档不存在", status_code=404, details={"document_id": document_id}) from exc
