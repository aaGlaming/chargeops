from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

class RagSection(BaseModel):
    id: int | None = None
    section_index: int
    block_type: Literal["heading", "paragraph", "list_item", "table", "clause", "code_fence"]
    heading_path: str | None = None
    content: str
    start_char: int
    end_char: int
    metadata: dict[str, object] = Field(default_factory=dict)


class RagDocumentSummary(BaseModel):
    id: int
    document_key: str
    title: str
    doc_type: str
    source_type: str
    source_url: str | None = None
    original_file: str
    region_code: str | None = None
    version: str
    effective_date: date | None = None
    file_sha256: str
    parse_status: str
    parse_error: str | None = None
    vector_status: str
    embedding_model: str | None = None
    chunk_count: int = 0
    uploaded_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RagDocumentDetail(RagDocumentSummary):
    sections: list[RagSection] = Field(default_factory=list)
    section_count: int = 0


class RagDocumentListResponse(BaseModel):
    items: list[RagDocumentSummary]
    page: dict[str, int | bool]


class RagUploadResponse(BaseModel):
    document: RagDocumentDetail
    duplicate: bool = False
    message: str


class RagChunkRequest(BaseModel):
    target_tokens: int = Field(default=800, ge=64, le=8192)
    overlap_tokens: int = Field(default=120, ge=0, le=2048)


class RagChunkItem(BaseModel):
    id: int | None = None
    chunk_id: str
    chunk_index: int
    heading_path: str | None = None
    content: str
    start_char: int
    end_char: int
    estimated_tokens: int
    document_version: str
    validation_status: Literal["VALID", "INVALID"]
    validation_issues: list[str] = Field(default_factory=list)
    original_href: str
    metadata: dict[str, object] = Field(default_factory=dict)


class RagChunkBatchSummary(BaseModel):
    id: int
    batch_key: str
    document_id: int
    document_version: str
    cleaning_version: str
    target_tokens: int
    overlap_tokens: int
    status: str
    chunk_count: int
    invalid_count: int
    created_by: int | None = None
    created_at: datetime | None = None


class RagChunkBatchResponse(BaseModel):
    batch: RagChunkBatchSummary
    chunks: list[RagChunkItem]


class RagChunkBatchListResponse(BaseModel):
    items: list[RagChunkBatchSummary]


class RagOriginalFragment(BaseModel):
    document_id: int
    start_char: int
    end_char: int
    content: str


class RagEmbeddingRequest(BaseModel):
    chunk_batch_key: str | None = None
    force: bool = False


class RagEmbeddingBatchSummary(BaseModel):
    id: int
    batch_key: str
    document_id: int
    chunk_batch_id: int | None = None
    document_version: str
    embedding_model: str
    model_version: str | None = None
    status: str
    requested_count: int
    success_count: int
    failed_count: int
    pending_retry_count: int
    parameters: dict[str, object] = Field(default_factory=dict)
    error_message: str | None = None
    created_by: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None


class RagEmbeddingItemSummary(BaseModel):
    id: int
    chunk_id: int
    chunk_key: str
    chroma_id: str
    status: str
    attempt_count: int
    vector_dimension: int | None = None
    error_code: str | None = None
    error_message: str | None = None


class RagEmbeddingBatchResponse(BaseModel):
    batch: RagEmbeddingBatchSummary
    items: list[RagEmbeddingItemSummary] = Field(default_factory=list)


class RagEmbeddingBatchListResponse(BaseModel):
    items: list[RagEmbeddingBatchSummary]


class RagSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=50)
    doc_type: str | None = Field(default=None, max_length=64)
    region_code: str | None = Field(default=None, max_length=32)
    version: str | None = Field(default=None, max_length=64)
    effective_date_from: date | None = None
    effective_date_to: date | None = None
    agent_scenario: str | None = Field(default=None, max_length=128)
    use_vector: bool = True
    use_keyword: bool = True
    use_rerank: bool = False


class RagSearchHit(BaseModel):
    chunk_id: str
    document_id: int
    title: str
    doc_type: str
    source_type: str
    source_url: str | None = None
    region_code: str | None = None
    version: str
    effective_date: date | None = None
    chunk_index: int
    start_char: int
    end_char: int
    content: str
    original_fragment: str
    original_href: str
    vector_score: float | None = None
    keyword_score: float | None = None
    rerank_score: float | None = None
    score: float
    match_sources: list[Literal["vector", "keyword"]] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class RagSearchResponse(BaseModel):
    run_id: str
    query: str
    rewritten_query: str
    query_rewrite: dict[str, object] = Field(default_factory=dict)
    filters: dict[str, object] = Field(default_factory=dict)
    top_k: int
    status: Literal["HIT", "NO_HIT", "EVIDENCE_INSUFFICIENT"]
    vector_count: int
    keyword_count: int
    rerank_applied: bool = False
    warnings: list[str] = Field(default_factory=list)
    hits: list[RagSearchHit] = Field(default_factory=list)
    created_at: datetime | None = None
