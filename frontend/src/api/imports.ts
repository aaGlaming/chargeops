import { request } from './http'

export interface ImportBatchApi {
  id: number
  batch_key: string
  dataset_type: string
  source_type: string
  source_file?: string | null
  source_sha256?: string | null
  data_version: string
  row_count: number
  success_count: number
  failed_count: number
  skipped_count: number
  status: 'PENDING' | 'IMPORTED' | 'PARTIAL' | 'FAILED' | 'ROLLED_BACK'
  rollback_status: 'NOT_REQUESTED' | 'ROLLED_BACK'
  created_at: string
  completed_at?: string | null
  errors?: Array<Record<string, unknown>>
}

export interface ImportBatchRequest {
  dataset_type: string
  file_name: string
  data_version: string
  mapping: Record<string, string>
  rows: Array<Record<string, string>>
}

export function listImportBatches() {
  return request<{ items: ImportBatchApi[]; page: Record<string, number | boolean> }>({ method: 'GET', url: '/imports' })
}

export function createImportBatch(payload: ImportBatchRequest) {
  return request<ImportBatchApi>({ method: 'POST', url: '/imports', data: payload, timeout: 120_000 })
}

export function rollbackImportBatch(batchId: number) {
  return request<ImportBatchApi>({ method: 'POST', url: `/imports/${batchId}/rollback`, data: {} })
}

