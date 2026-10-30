import { http, request } from './http'

export interface RagDocument {
  id: number
  document_key: string
  title: string
  doc_type: string
  source_type: string
  source_url?: string | null
  original_file: string
  region_code?: string | null
  version: string
  effective_date?: string | null
  file_sha256: string
  parse_status: string
  parse_error?: string | null
  vector_status: string
  embedding_model?: string | null
  chunk_count: number
  uploaded_by?: number | null
  created_at?: string | null
  updated_at?: string | null
}

export interface RagSection {
  id?: number | null
  section_index: number
  block_type: string
  heading_path?: string | null
  content: string
  start_char: number
  end_char: number
  metadata: Record<string, unknown>
}

export interface RagDocumentDetail extends RagDocument {
  sections: RagSection[]
  section_count: number
}

export interface ChunkItem {
  id?: number | null
  chunk_id: string
  chunk_index: number
  heading_path?: string | null
  content: string
  start_char: number
  end_char: number
  estimated_tokens: number
  document_version: string
  validation_status: string
  validation_issues: string[]
  original_href: string
  metadata: Record<string, unknown>
}

export interface ChunkBatch {
  id: number
  batch_key: string
  document_id: number
  document_version: string
  cleaning_version: string
  target_tokens: number
  overlap_tokens: number
  status: string
  chunk_count: number
  invalid_count: number
  created_by?: number | null
  created_at?: string | null
}

export interface ChunkBatchResponse { batch: ChunkBatch; chunks: ChunkItem[] }

export interface EmbeddingBatch {
  id: number
  batch_key: string
  document_id: number
  chunk_batch_id?: number | null
  document_version: string
  embedding_model: string
  model_version?: string | null
  status: string
  requested_count: number
  success_count: number
  failed_count: number
  pending_retry_count: number
  parameters: Record<string, unknown>
  error_message?: string | null
  created_by?: number | null
  started_at?: string | null
  completed_at?: string | null
  created_at?: string | null
}

export interface EmbeddingBatchResponse { batch: EmbeddingBatch; items: Array<Record<string, unknown>> }

export interface RagHit {
  chunk_id: string
  document_id: number
  title: string
  doc_type: string
  source_type: string
  source_url?: string | null
  region_code?: string | null
  version: string
  effective_date?: string | null
  chunk_index: number
  start_char: number
  end_char: number
  content: string
  original_fragment: string
  original_href: string
  vector_score?: number | null
  keyword_score?: number | null
  rerank_score?: number | null
  score: number
  match_sources: string[]
  metadata: Record<string, unknown>
}

export interface RagSearchResponse {
  run_id: string
  query: string
  rewritten_query: string
  query_rewrite: Record<string, unknown>
  filters: Record<string, unknown>
  top_k: number
  status: string
  vector_count: number
  keyword_count: number
  rerank_applied: boolean
  warnings: string[]
  hits: RagHit[]
  created_at?: string | null
}

export function listRagDocuments(params: { doc_type?: string; parse_status?: string; vector_status?: string; region_code?: string; page?: number; page_size?: number } = {}) {
  return request<{ items: RagDocument[]; page: Record<string, number | boolean> }>({ method: 'GET', url: '/rag/documents', params })
}

export async function uploadRagDocument(file: File, metadata: { title?: string; doc_type: string; source_type: string; source_url?: string; region_code?: string; version: string; effective_date?: string }, onProgress?: (value: number) => void) {
  const body = new FormData()
  body.append('file', file)
  Object.entries(metadata).forEach(([key, value]) => { if (value) body.append(key, value) })
  const response = await http.post<{ document: RagDocumentDetail; duplicate: boolean; message: string }>('/rag/documents', body, { onUploadProgress: (event) => { if (event.total) onProgress?.(Math.round(event.loaded / event.total * 100)) } })
  return response.data
}

export function getRagDocument(documentId: number) {
  return request<RagDocumentDetail>({ method: 'GET', url: `/rag/documents/${documentId}` })
}

export function retryRagDocument(documentId: number) {
  return request<RagDocumentDetail>({ method: 'POST', url: `/rag/documents/${documentId}/retry` })
}

export function listChunkBatches(documentId: number) {
  return request<{ items: ChunkBatch[] }>({ method: 'GET', url: `/rag/documents/${documentId}/chunks/batches` })
}

export function previewRagChunks(documentId: number, targetTokens: number, overlapTokens: number, rebuild = false) {
  return request<ChunkBatchResponse>({ method: 'POST', url: `/rag/documents/${documentId}/chunks/${rebuild ? 'rebuild' : 'preview'}`, data: { target_tokens: targetTokens, overlap_tokens: overlapTokens } })
}

export function getChunkPreview(documentId: number, batchKey?: string) {
  return request<ChunkBatchResponse>({ method: 'GET', url: `/rag/documents/${documentId}/chunks/preview`, params: { batch_key: batchKey } })
}

export function listEmbeddingBatches(documentId?: number) {
  return request<{ items: EmbeddingBatch[] }>({ method: 'GET', url: '/rag/embedding-batches', params: documentId ? { document_id: documentId } : undefined })
}

export function embedRagDocument(documentId: number, chunkBatchKey?: string, force = false) {
  return request<EmbeddingBatchResponse>({ method: 'POST', url: `/rag/documents/${documentId}/embeddings`, data: { chunk_batch_key: chunkBatchKey, force } })
}

export function rebuildRagEmbedding(documentId: number, chunkBatchKey?: string) {
  return request<EmbeddingBatchResponse>({ method: 'POST', url: `/rag/documents/${documentId}/embeddings/rebuild`, data: { chunk_batch_key: chunkBatchKey, force: true } })
}

export function retryRagEmbedding(batchId: number) {
  return request<EmbeddingBatchResponse>({ method: 'POST', url: `/rag/embedding-batches/${batchId}/retry` })
}

export function searchRag(payload: { query: string; top_k: number; doc_type?: string; region_code?: string; version?: string; agent_scenario?: string; use_vector: boolean; use_keyword: boolean; use_rerank: boolean }) {
  return request<RagSearchResponse>({ method: 'POST', url: '/rag/search', data: payload })
}

