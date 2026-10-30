import { request } from './http'

export interface AuditLogItem {
  id: number
  occurred_at: string
  actor_user_id?: number | null
  action: string
  resource_type: string
  resource_id?: string | null
  request_id?: string | null
  trace_id?: string | null
  agent_run_id?: string | null
  tool_call_id?: number | null
  import_batch_id?: number | null
  severity: string
  before_state?: Record<string, unknown> | null
  after_state?: Record<string, unknown> | null
  metadata?: Record<string, unknown> | null
}

export interface MonitoringOverview {
  generated_at: string
  readiness: { status: string; ready: boolean; checks: Array<{ service: string; status: string; detail: string; retryable?: boolean }> }
  telemetry: { request_count: number; error_count: number; error_rate: number; p95_latency_ms: number; components: Record<string, { count: number; error_count: number; p95_latency_ms: number }> }
  database: { status: string }
  disk: { total_bytes: number; used_bytes: number; free_bytes: number; used_ratio: number }
  models: Record<string, unknown>
  agent_runs: Record<string, number>
  imports: Record<string, number>
  audit: { total: number; warnings: number; last_24h: number }
  components: Record<string, { count: number; error_count: number; p95_latency_ms: number }>
}

export interface AlertState { code: string; label: string; severity: string; enabled: boolean; current_status: string; detail: string }

export function listAuditLogs(params: { page?: number; page_size?: number; action?: string; resource_type?: string; severity?: string; trace_id?: string; agent_run_id?: string; import_batch_id?: number } = {}) {
  return request<{ items: AuditLogItem[]; page: Record<string, number | boolean> }>({ method: 'GET', url: '/audit-logs', params })
}

export function getMonitoringOverview() {
  return request<MonitoringOverview>({ method: 'GET', url: '/monitoring/overview' })
}

export function listAlertStates() {
  return request<{ items: AlertState[] }>({ method: 'GET', url: '/monitoring/alerts' })
}

export function setAlertEnabled(code: string, enabled: boolean) {
  return request<{ items: AlertState[] }>({ method: 'POST', url: `/monitoring/alerts/${encodeURIComponent(code)}`, params: { enabled } })
}
