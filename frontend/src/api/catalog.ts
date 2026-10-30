import { request } from './http'

export interface SourceInfo {
  source_type: string
  source_url?: string | null
  source_file?: string | null
  data_version: string
  import_batch_id?: number | null
}

export interface RegionSummary {
  id: number
  region_code: string
  name: string
  parent_region_id?: number | null
  region_type?: string | null
  country_code?: string | null
  station_count: number
  source: SourceInfo
}

export interface OperatorSummary {
  id: number
  operator_code?: string | null
  operator_name: string
  station_count: number
  source: SourceInfo
}

export interface Station {
  id: number
  external_station_id: number
  external_station_key?: string | null
  station_name: string
  street_address?: string | null
  city?: string | null
  state?: string | null
  zip_code?: string | null
  country_code?: string | null
  latitude?: number | null
  longitude?: number | null
  station_status: string
  access_type: string
  facility_type?: string | null
  charging_types: string[]
  total_connector_count: number
  date_last_confirmed?: string | null
  effective_date?: string | null
  region?: RegionSummary | null
  operator?: OperatorSummary | null
  source: SourceInfo
}

export interface Connector {
  id: number
  station_id: number
  connector_type: string
  quantity: number
  power_kw?: number | null
  connector_status?: string | null
  source: SourceInfo
}

export interface StationDetail extends Station {
  connectors: Connector[]
  related: Record<string, number | string>
}

export interface MapPoint {
  id: number
  station_name: string
  latitude: number
  longitude: number
  station_status: string
  access_type: string
  total_connector_count: number
  source_type: string
  data_version: string
  region_code?: string | null
  operator_name?: string | null
}

export interface PageMeta {
  page: number
  page_size: number
  total: number
  has_next: boolean
}

export function listRegions(params: { region_code?: string; page?: number; page_size?: number } = {}) {
  return request<{ items: RegionSummary[]; page: PageMeta }>({ method: 'GET', url: '/regions', params })
}

export function getRegion(regionCode: string) {
  return request<RegionSummary & { boundary_geojson?: Record<string, unknown> | null; child_regions: RegionSummary[] }>({ method: 'GET', url: `/regions/${encodeURIComponent(regionCode)}` })
}

export function listOperators(params: { operator_name?: string; page?: number; page_size?: number } = {}) {
  return request<{ items: OperatorSummary[]; page: PageMeta }>({ method: 'GET', url: '/operators', params })
}

export interface StationQueryParams {
  region_code?: string
  operator_id?: number
  charging_type?: string
  station_status?: string
  access_type?: string
  source_type?: string
  data_version?: string
  page?: number
  page_size?: number
}

export function listStations(params: StationQueryParams = {}) {
  return request<{ items: Station[]; page: PageMeta }>({ method: 'GET', url: '/stations', params })
}

export function listStationMapPoints(params: StationQueryParams = {}) {
  return request<{ items: MapPoint[]; total: number }>({ method: 'GET', url: '/stations/map-points', params: { ...params, limit: 5000 } })
}

export function getStation(stationId: number) {
  return request<StationDetail>({ method: 'GET', url: `/stations/${stationId}` })
}

export function listConnectors(params: { station_id?: number; connector_type?: string; connector_status?: string; page?: number; page_size?: number } = {}) {
  return request<{ items: Connector[]; page: PageMeta }>({ method: 'GET', url: '/connectors', params })
}

export function listStationConnectors(stationId: number) {
  return request<{ items: Connector[]; page: PageMeta }>({ method: 'GET', url: `/stations/${stationId}/connectors`, params: { page: 1, page_size: 500 } })
}

