import { request } from './http'
import type { PageMeta, RegionSummary, SourceInfo, Station } from './catalog'

export interface Metric {
  id: number
  station_id: number
  metric_date: string
  metric_hour?: number | null
  timezone: string
  charging_sessions?: number | null
  energy_kwh?: number | null
  peak_power_kw?: number | null
  occupancy_rate?: number | null
  avg_session_minutes?: number | null
  data_as_of?: string | null
  source: SourceInfo
}

export interface Fault {
  id: number
  station_id: number
  external_fault_id?: string | null
  fault_type: string
  severity: string
  started_at: string
  recovered_at?: string | null
  affected_connectors?: number | null
  root_cause?: string | null
  status: string
  data_as_of?: string | null
  source: SourceInfo
}

export interface Candidate {
  id: number
  external_candidate_id: string
  site_name: string
  region?: RegionSummary | null
  city?: string | null
  state?: string | null
  latitude?: number | null
  longitude?: number | null
  area_sqm?: number | null
  parking_spaces?: number | null
  electric_capacity_kw?: number | null
  budget_usd?: number | null
  traffic_index?: number | null
  population_density?: number | null
  planned_open_date?: string | null
  data_as_of?: string | null
  data_status: string
  lifecycle_status: string
  completeness: { score: number; missing_fields: string[]; evaluable: boolean; recommendable: boolean }
  freshness: { data_as_of?: string | null; age_days?: number | null; status: string }
  source: SourceInfo
}

export interface CandidateDetail extends Candidate {
  nearby_stations: Station[]
  policies: Array<Record<string, unknown>>
  related: Record<string, number | string>
}

export interface CandidatePayload {
  external_candidate_id?: string
  site_name?: string
  region_code?: string
  city?: string
  state?: string
  latitude?: number | null
  longitude?: number | null
  area_sqm?: number | null
  parking_spaces?: number | null
  electric_capacity_kw?: number | null
  budget_usd?: number | null
  traffic_index?: number | null
  population_density?: number | null
  planned_open_date?: string | null
  data_as_of?: string | null
  lifecycle_status?: string
  source_type?: string
  data_version?: string
}

export function listMetrics(stationId: number, params: { page?: number; page_size?: number } = {}) {
  return request<{ items: Metric[]; page: PageMeta }>({ method: 'GET', url: `/stations/${stationId}/metrics`, params: { page: 1, page_size: 30, ...params } })
}

export function listFaults(stationId: number, params: { page?: number; page_size?: number } = {}) {
  return request<{ items: Fault[]; page: PageMeta }>({ method: 'GET', url: `/stations/${stationId}/faults`, params: { page: 1, page_size: 30, ...params } })
}

export function listCandidates(params: { region_code?: string; lifecycle_status?: string; data_status?: string; page?: number; page_size?: number } = {}) {
  return request<{ items: Candidate[]; page: PageMeta }>({ method: 'GET', url: '/candidate-sites', params })
}

export function getCandidate(candidateId: number) {
  return request<CandidateDetail>({ method: 'GET', url: `/candidate-sites/${candidateId}` })
}

export function createCandidate(payload: CandidatePayload) {
  return request<CandidateDetail>({ method: 'POST', url: '/candidate-sites', data: payload })
}

export function updateCandidate(candidateId: number, payload: CandidatePayload) {
  return request<CandidateDetail>({ method: 'PATCH', url: `/candidate-sites/${candidateId}`, data: payload })
}

export function deleteCandidate(candidateId: number) {
  return request<void>({ method: 'DELETE', url: `/candidate-sites/${candidateId}` })
}

