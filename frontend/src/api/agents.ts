import { request } from './http'

export type AgentType = 'coverage_gap' | 'competition' | 'site_selection' | 'expansion' | 'policy_matching'

export interface AgentEvent {
  id: number
  run_id: string
  sequence_no: number
  event_type: string
  status: string
  provider?: string | null
  model_name?: string | null
  confirmation_type?: string | null
  input_summary: Record<string, unknown>
  output_summary: Record<string, unknown>
  error_code?: string | null
  retryable: boolean
  duration_ms?: number | null
  started_at?: string | null
  finished_at?: string | null
}

export interface ToolCall {
  id: number
  run_id: string
  sequence_no: number
  tool_name: string
  permission_code?: string | null
  risk_level: string
  input_summary: Record<string, unknown>
  output_summary: Record<string, unknown>
  status: string
  error_code?: string | null
  retryable: boolean
  duration_ms?: number | null
  started_at?: string | null
  finished_at?: string | null
}

export interface AgentRun {
  run_id: string
  agent_type: AgentType
  requested_by: number
  status: string
  data_version?: string | null
  prompt_version?: string | null
  model_name?: string | null
  embedding_model?: string | null
  stop_reason?: string | null
  confirmation_status: string
  started_at?: string | null
  finished_at?: string | null
  created_at: string
  updated_at: string
  input_payload: Record<string, unknown>
  business_scope: Record<string, unknown>
  evidence_summary: Record<string, unknown>
  state_snapshot: {
    status?: string
    current_stage?: string
    retrieval_queries?: Array<Record<string, unknown>>
    evidence?: Array<Record<string, unknown>>
    tool_results?: Record<string, unknown>
    calculation_results?: Record<string, unknown>
    conclusion?: Record<string, unknown> | null
    errors?: Array<Record<string, unknown>>
    confirmation_status?: string
    iteration?: number
    tool_call_count?: number
    model_call_count?: number
  }
  tool_calls: ToolCall[]
  events: AgentEvent[]
}

export function createAgentRun(payload: { agent_type: AgentType; input_payload: Record<string, unknown>; business_scope?: Record<string, unknown>; data_version?: string; prompt_version?: string }) {
  return request<AgentRun>({ method: 'POST', url: '/agent-runs', data: payload })
}

export function executeAgentRun(runId: string, limits: { max_model_calls?: number; max_tool_calls?: number; max_loop_iterations?: number; max_duration_seconds?: number } = {}) {
  return request<AgentRun>({ method: 'POST', url: `/agent-runs/${runId}/execute`, data: limits })
}

export function getAgentRun(runId: string) {
  return request<AgentRun>({ method: 'GET', url: `/agent-runs/${runId}` })
}

export function cancelAgentRun(runId: string) {
  return request<AgentRun>({ method: 'POST', url: `/agent-runs/${runId}/cancel` })
}

export function retryAgentRun(runId: string, limits: Record<string, number> = {}) {
  return request<AgentRun>({ method: 'POST', url: `/agent-runs/${runId}/retry`, data: limits })
}

export function confirmAgentRun(runId: string, decision: 'APPROVE' | 'REJECT', comment: string) {
  return request<AgentRun>({ method: 'POST', url: `/agent-runs/${runId}/confirmation`, data: { decision, comment } })
}

