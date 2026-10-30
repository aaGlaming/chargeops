import { http, request } from './http'

export interface Report {
  report_id: string
  run_id: string
  report_type: string
  title: string
  status: string
  conclusion?: string | null
  calculation_summary: Record<string, unknown>
  business_data: Record<string, unknown>
  rag_evidence: Array<Record<string, unknown>>
  confirmation_type?: string | null
  confirmation_comment?: string | null
  rejection_reason?: string | null
  data_version?: string | null
  created_at: string
  updated_at: string
}

export function createReport(runId: string, title?: string) {
  return request<Report>({ method: 'POST', url: '/reports', data: { run_id: runId, title } })
}

export function getReport(reportId: string) {
  return request<Report>({ method: 'GET', url: `/reports/${reportId}` })
}

export function confirmReport(reportId: string, decision: 'APPROVE' | 'REJECT', comment: string) {
  return request<Report>({ method: 'POST', url: `/reports/${reportId}/confirmation`, data: { decision, comment } })
}

export async function downloadReport(reportId: string, format: 'markdown' | 'json') {
  const response = await http.get(`/reports/${reportId}/export`, { params: { format }, responseType: 'blob' })
  const url = URL.createObjectURL(response.data)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `chargeops-${reportId}.${format === 'markdown' ? 'md' : 'json'}`
  anchor.click()
  URL.revokeObjectURL(url)
}

