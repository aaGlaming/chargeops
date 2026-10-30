<script setup lang="ts">
import { computed, onMounted, reactive, shallowRef } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight } from '@element-plus/icons-vue'
import EChartCard from '../components/common/EChartCard.vue'
import { getApiError } from '../api/http'
import { listAgentRuns, type AgentRunSummary } from '../api/agents'
import { listConnectors, listOperators, listRegions, listStationMapPoints, listStations, type Connector, type MapPoint, type OperatorSummary, type RegionSummary, type Station } from '../api/catalog'
import { listFaults, listMetrics, type Fault, type Metric, listCandidates, type Candidate } from '../api/operations'
import { listReports, type ReportSummary } from '../api/reports'
import type { EChartsOption } from 'echarts'

const router = useRouter()
const loading = shallowRef(false)
const lastUpdated = shallowRef('未加载')
const errorMessage = shallowRef('')
const traceId = shallowRef('')
const filters = reactive({ regionCode: '', days: 30 })
const chartErrors = reactive<Record<string, string>>({})
const points = shallowRef<MapPoint[]>([])
const stations = shallowRef<Station[]>([])
const regions = shallowRef<RegionSummary[]>([])
const operators = shallowRef<OperatorSummary[]>([])
const connectors = shallowRef<Connector[]>([])
const metrics = shallowRef<Metric[]>([])
const faults = shallowRef<Fault[]>([])
const candidates = shallowRef<Candidate[]>([])
const candidatesTotal = shallowRef(0)
const runs = shallowRef<AgentRunSummary[]>([])
const reports = shallowRef<ReportSummary[]>([])
const stationTotal = shallowRef(0)
const connectorRowTotal = shallowRef(0)

const palette = ['#3563e9', '#23a889', '#e2a33c', '#8a63d7', '#dd6d78', '#5b91d5', '#46b48c', '#9b7ade']
const regionOptions = computed(() => regions.value.filter((region) => region.region_code))
const stationById = computed(() => new Map(stations.value.map((station) => [station.id, station])))
const connectorTotal = computed(() => {
  const quantity = connectors.value.reduce((sum, connector) => sum + Number(connector.quantity || 0), 0)
  return quantity || connectorRowTotal.value
})
const fastConnectorRatio = computed(() => {
  const isFast = (value: string) => /DC|FAST|CHADEMO|CCS|TESLA/i.test(value)
  const fast = connectors.value.filter((connector) => isFast(connector.connector_type)).reduce((sum, connector) => sum + Number(connector.quantity || 0), 0)
  const total = connectors.value.reduce((sum, connector) => sum + Number(connector.quantity || 0), 0)
  if (total) return Math.round(fast / total * 100)
  const fastStations = stations.value.filter((station) => station.charging_types.some(isFast)).length
  return stations.value.length ? Math.round(fastStations / stations.value.length * 100) : 0
})
const highRiskStations = computed(() => {
  const ids = new Set<number>()
  faults.value.forEach((fault) => { if (['HIGH', 'CRITICAL'].includes(fault.severity) || fault.status === 'OPEN') ids.add(fault.station_id) })
  metrics.value.forEach((metric) => { if (Number(metric.occupancy_rate || 0) >= 0.9) ids.add(metric.station_id) })
  return ids
})
const pendingConfirmationCount = computed(() => reports.value.filter((report) => report.status === 'WAITING_CONFIRMATION').length || runs.value.filter((run) => run.confirmation_status === 'WAITING_CONFIRMATION').length)
const chartEmpty = (key: string, values: unknown[]) => !loading.value && !chartErrors[key] && values.length === 0

async function loadPart<T>(key: string, action: () => Promise<T>, fallback: T) {
  try {
    delete chartErrors[key]
    return await action()
  } catch (error) {
    const detail = getApiError(error)
    chartErrors[key] = detail.message
    if (!traceId.value) traceId.value = detail.traceId
    return fallback
  }
}

async function loadDashboard() {
  loading.value = true
  errorMessage.value = ''
  traceId.value = ''
  Object.keys(chartErrors).forEach((key) => delete chartErrors[key])
  const startDate = new Date(Date.now() - filters.days * 86400000).toISOString().slice(0, 10)
  const stationParams = { region_code: filters.regionCode || undefined, page: 1, page_size: 200 }
  const [mapResponse, stationResponse, regionResponse, operatorResponse, connectorResponse, metricResponse, faultResponse, candidateResponse, runResponse, reportResponse] = await Promise.all([
    loadPart('map', () => listStationMapPoints(stationParams), { items: [], total: 0 }),
    loadPart('stations', () => listStations(stationParams), { items: [], page: { page: 1, page_size: 200, total: 0, has_next: false } }),
    loadPart('regions', () => listRegions({ page: 1, page_size: 200 }), { items: [], page: { page: 1, page_size: 200, total: 0, has_next: false } }),
    loadPart('operators', () => listOperators({ page: 1, page_size: 200 }), { items: [], page: { page: 1, page_size: 200, total: 0, has_next: false } }),
    loadPart('connectors', () => listConnectors({ page: 1, page_size: 500 }), { items: [], page: { page: 1, page_size: 500, total: 0, has_next: false } }),
    loadPart('trend', () => listMetrics(undefined, { page: 1, page_size: 500, start_date: startDate }), { items: [], page: { page: 1, page_size: 500, total: 0, has_next: false } }),
    loadPart('faults', () => listFaults(undefined, { page: 1, page_size: 500, started_from: `${startDate}T00:00:00` }), { items: [], page: { page: 1, page_size: 500, total: 0, has_next: false } }),
    loadPart('candidates', () => listCandidates({ region_code: filters.regionCode || undefined, page: 1, page_size: 200 }), { items: [], page: { page: 1, page_size: 200, total: 0, has_next: false } }),
    loadPart('runs', () => listAgentRuns(), { items: [] }),
    loadPart('reports', () => listReports(), { items: [] }),
  ])
  points.value = mapResponse.items
  stations.value = stationResponse.items
  stationTotal.value = Number(stationResponse.page.total || mapResponse.total || 0)
  regions.value = regionResponse.items
  operators.value = operatorResponse.items
  connectors.value = connectorResponse.items
  connectorRowTotal.value = Number(connectorResponse.page.total || 0)
  metrics.value = metricResponse.items.filter((metric) => !filters.regionCode || stationById.value.has(metric.station_id))
  faults.value = faultResponse.items.filter((fault) => !filters.regionCode || stationById.value.has(fault.station_id))
  candidates.value = candidateResponse.items
  candidatesTotal.value = Number(candidateResponse.page.total || 0)
  runs.value = runResponse.items
  reports.value = reportResponse.items
  const failedParts = Object.keys(chartErrors)
  if (failedParts.length === 10) errorMessage.value = '驾驶舱数据全部加载失败，请检查 API 服务或权限。'
  lastUpdated.value = new Date().toLocaleString('zh-CN', { hour12: false })
  loading.value = false
}

function handleChartClick(payload: any) {
  if (payload?.action === 'retry') { loadDashboard(); return }
  const data = payload?.data || {}
  if (data.stationId) router.push({ name: 'stations', query: { station_id: String(data.stationId) } })
  else if (data.regionCode) router.push({ name: 'regions', query: { region_code: String(data.regionCode) } })
  else if (data.candidateId) router.push({ name: 'candidates', query: { candidate_id: String(data.candidateId) } })
  else if (data.operatorId) router.push({ name: 'stations', query: { operator_id: String(data.operatorId) } })
}

function openStation(stationId: number) { router.push({ name: 'stations', query: { station_id: String(stationId) } }) }

const mapOption = computed<EChartsOption>(() => {
  const operatorNames = [...new Set(points.value.map((point) => point.operator_name || '未标注'))].slice(0, palette.length)
  const series = operatorNames.map((operatorName, index) => ({ name: operatorName, type: 'scatter' as const, symbolSize: (value: number[]) => Math.max(7, Math.min(18, 7 + Math.sqrt(Number(value[2] || 1)))), itemStyle: { color: palette[index] }, data: points.value.filter((point) => (point.operator_name || '未标注') === operatorName).map((point) => ({ value: [point.longitude, point.latitude, point.total_connector_count], stationId: point.id, name: point.station_name, operator: operatorName })) }))
  return { animation: false, legend: { type: 'scroll', top: 0, textStyle: { color: '#78869a', fontSize: 10 } }, grid: { left: 55, right: 18, top: 34, bottom: 36 }, tooltip: { trigger: 'item', formatter: (params: any) => `${params.data?.name || '站点'}<br/>运营商：${params.data?.operator || '-'}<br/>经度：${params.data?.value?.[0] ?? '-'} · 纬度：${params.data?.value?.[1] ?? '-'}` }, xAxis: { type: 'value', name: '经度', scale: true, axisLabel: { color: '#8b98aa', fontSize: 10 }, splitLine: { lineStyle: { color: '#eef1f5' } } }, yAxis: { type: 'value', name: '纬度', scale: true, axisLabel: { color: '#8b98aa', fontSize: 10 }, splitLine: { lineStyle: { color: '#eef1f5' } } }, series }
})

const coverageOption = computed<EChartsOption>(() => {
  const maxStations = Math.max(...regions.value.map((region) => region.station_count), 1)
  const data = regions.value.slice(0, 30).map((region, index) => [0, index, Math.round((1 - region.station_count / maxStations) * 100), region.region_code, region.name])
  return { animation: false, grid: { left: 108, right: 46, top: 10, bottom: 25 }, tooltip: { formatter: (params: any) => `${params.data?.[4] || '-'}<br/>相对缺口指数：${params.data?.[2] ?? 0}` }, xAxis: { type: 'category', data: ['缺口指数'], axisLabel: { color: '#8b98aa', fontSize: 10 } }, yAxis: { type: 'category', data: regions.value.slice(0, 30).map((region) => region.name), axisLabel: { color: '#78869a', fontSize: 10 } }, visualMap: { min: 0, max: 100, calculable: false, orient: 'horizontal', right: 0, top: -4, textStyle: { color: '#8b98aa', fontSize: 9 }, inRange: { color: ['#dff5ed', '#f0c76d', '#d95d6c'] } }, series: [{ type: 'heatmap', data }] }
})

const operatorOption = computed<EChartsOption>(() => ({ animation: false, grid: { left: 94, right: 20, top: 12, bottom: 30 }, tooltip: { trigger: 'axis' }, xAxis: { type: 'value', axisLabel: { color: '#8b98aa', fontSize: 10 }, splitLine: { lineStyle: { color: '#eef1f5' } } }, yAxis: { type: 'category', inverse: true, data: operators.value.slice(0, 10).map((operator) => operator.operator_name), axisLabel: { color: '#78869a', fontSize: 10, width: 88, overflow: 'truncate' } }, series: [{ type: 'bar', data: operators.value.slice(0, 10).map((operator) => ({ value: operator.station_count, operatorId: operator.id, name: operator.operator_name })), itemStyle: { color: '#3563e9', borderRadius: [0, 5, 5, 0] }, barMaxWidth: 16 }] }))

const chargingTypeOption = computed<EChartsOption>(() => {
  const counts = new Map<string, number>()
  stations.value.forEach((station) => station.charging_types.forEach((type) => counts.set(type, (counts.get(type) || 0) + 1)))
  return { animation: false, tooltip: { trigger: 'item' }, legend: { bottom: 0, textStyle: { color: '#78869a', fontSize: 10 } }, series: [{ type: 'pie', radius: ['42%', '72%'], center: ['50%', '45%'], label: { show: false }, data: [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8).map(([name, value], index) => ({ name, value, itemStyle: { color: palette[index % palette.length] } })) }] }
})

const trendOption = computed<EChartsOption>(() => {
  const grouped = new Map<string, { sessions: number; energy: number; occupancy: number[] }>()
  metrics.value.forEach((metric) => { const item = grouped.get(metric.metric_date) || { sessions: 0, energy: 0, occupancy: [] }; item.sessions += Number(metric.charging_sessions || 0); item.energy += Number(metric.energy_kwh || 0); if (metric.occupancy_rate != null) item.occupancy.push(Number(metric.occupancy_rate) * 100); grouped.set(metric.metric_date, item) })
  const dates = [...grouped.keys()].sort()
  return { animation: false, legend: { top: 0, textStyle: { color: '#78869a', fontSize: 10 } }, grid: { left: 45, right: 18, top: 30, bottom: 30 }, tooltip: { trigger: 'axis' }, xAxis: { type: 'category', data: dates, axisLabel: { color: '#8b98aa', fontSize: 9 } }, yAxis: [{ type: 'value', name: '会话', axisLabel: { color: '#8b98aa', fontSize: 9 }, splitLine: { lineStyle: { color: '#eef1f5' } } }, { type: 'value', name: '利用率 %', axisLabel: { color: '#8b98aa', fontSize: 9 } }], series: [{ name: '充电会话', type: 'line', smooth: true, showSymbol: false, data: dates.map((date) => grouped.get(date)?.sessions || 0), lineStyle: { color: '#3563e9', width: 2 }, areaStyle: { color: 'rgba(53,99,233,.10)' } }, { name: '能耗 kWh', type: 'line', smooth: true, showSymbol: false, data: dates.map((date) => Math.round(grouped.get(date)?.energy || 0)), lineStyle: { color: '#23a889', width: 2 } }, { name: '平均利用率', type: 'line', yAxisIndex: 1, smooth: true, showSymbol: false, data: dates.map((date) => { const values = grouped.get(date)?.occupancy || []; return values.length ? Math.round(values.reduce((sum, value) => sum + value, 0) / values.length) : 0 }), lineStyle: { color: '#e2a33c', width: 2 } }] }
})

const faultOption = computed<EChartsOption>(() => {
  const grouped = new Map<string, { open: number; recovered: number }>()
  faults.value.forEach((fault) => { const date = fault.started_at.slice(0, 10); const item = grouped.get(date) || { open: 0, recovered: 0 }; item.open += 1; if (fault.recovered_at || fault.status !== 'OPEN') item.recovered += 1; grouped.set(date, item) })
  const dates = [...grouped.keys()].sort()
  return { animation: false, legend: { top: 0, textStyle: { color: '#78869a', fontSize: 10 } }, grid: { left: 40, right: 18, top: 30, bottom: 30 }, tooltip: { trigger: 'axis' }, xAxis: { type: 'category', data: dates, axisLabel: { color: '#8b98aa', fontSize: 9 } }, yAxis: { type: 'value', minInterval: 1, axisLabel: { color: '#8b98aa', fontSize: 9 }, splitLine: { lineStyle: { color: '#eef1f5' } } }, series: [{ name: '故障发生', type: 'bar', stack: 'fault', data: dates.map((date) => grouped.get(date)?.open || 0), itemStyle: { color: '#dd6d78' } }, { name: '已恢复', type: 'bar', stack: 'recovered', data: dates.map((date) => grouped.get(date)?.recovered || 0), itemStyle: { color: '#35bd88' } }] }
})

const bestCandidate = computed(() => [...candidates.value].sort((a, b) => b.completeness.score - a.completeness.score)[0] || null)
const candidateRadarOption = computed<EChartsOption>(() => {
  const candidate = bestCandidate.value
  const maxTraffic = Math.max(...candidates.value.map((item) => Number(item.traffic_index || 0)), 1)
  const maxPopulation = Math.max(...candidates.value.map((item) => Number(item.population_density || 0)), 1)
  const maxCapacity = Math.max(...candidates.value.map((item) => Number(item.electric_capacity_kw || 0)), 1)
  const values = candidate ? [Math.round(candidate.completeness.score * 100), Math.round(Number(candidate.traffic_index || 0) / maxTraffic * 100), Math.round(Number(candidate.population_density || 0) / maxPopulation * 100), Math.round(Number(candidate.electric_capacity_kw || 0) / maxCapacity * 100), candidate.freshness.status === 'CURRENT' ? 100 : 50] : []
  return { animation: false, tooltip: { trigger: 'item' }, radar: { radius: '63%', indicator: [{ name: '数据完整', max: 100 }, { name: '交通', max: 100 }, { name: '人口', max: 100 }, { name: '电力', max: 100 }, { name: '时效', max: 100 }], axisName: { color: '#78869a', fontSize: 10 }, splitLine: { lineStyle: { color: '#e6ebf2' } }, splitArea: { areaStyle: { color: ['#fbfcfe', '#f6f8fc'] } } }, series: [{ type: 'radar', data: candidate ? [{ value: values, name: candidate.site_name, candidateId: candidate.id, areaStyle: { color: 'rgba(53,99,233,.18)' }, lineStyle: { color: '#3563e9' }, itemStyle: { color: '#3563e9' } }] : [] }] }
})

const competitionOption = computed<EChartsOption>(() => ({ animation: false, grid: { left: 50, right: 24, top: 20, bottom: 38 }, tooltip: { trigger: 'item', formatter: (params: any) => `${params.data?.name || '候选站点'}<br/>交通指数：${params.data?.value?.[0] ?? '-'}<br/>人口密度：${params.data?.value?.[1] ?? '-'}` }, xAxis: { type: 'value', name: '交通指数', axisLabel: { color: '#8b98aa', fontSize: 9 }, splitLine: { lineStyle: { color: '#eef1f5' } } }, yAxis: { type: 'value', name: '人口密度', axisLabel: { color: '#8b98aa', fontSize: 9 }, splitLine: { lineStyle: { color: '#eef1f5' } } }, series: [{ type: 'scatter', symbolSize: (value: number[]) => Math.max(10, Math.min(28, 8 + Number(value[2] || 0) * 18)), data: candidates.value.map((candidate) => ({ value: [candidate.traffic_index || 0, candidate.population_density || 0, candidate.completeness.score], name: candidate.site_name, candidateId: candidate.id, itemStyle: { color: candidate.lifecycle_status === 'RECOMMENDED' ? '#23a889' : '#8a63d7' } })) }] }))

const expansionPriorities = computed(() => {
  const scores = new Map<number, number>()
  faults.value.forEach((fault) => scores.set(fault.station_id, (scores.get(fault.station_id) || 0) + (fault.severity === 'CRITICAL' ? 45 : fault.severity === 'HIGH' ? 30 : 12) + (fault.status === 'OPEN' ? 15 : 0)))
  metrics.value.forEach((metric) => { if (metric.occupancy_rate != null) scores.set(metric.station_id, (scores.get(metric.station_id) || 0) + Math.round(Number(metric.occupancy_rate) * 40)) })
  return [...scores.entries()].map(([stationId, score]) => ({ stationId, score: Math.min(100, score), station: stationById.value.get(stationId) })).sort((a, b) => b.score - a.score).slice(0, 8)
})

onMounted(loadDashboard)
</script>

<template>
  <section class="dashboard-page dashboard-page--rich">
    <div class="dashboard-toolbar"><div><span class="eyebrow">OPERATIONS CONTROL TOWER</span><div class="data-freshness"><span class="status-dot" /> 数据更新时间：{{ lastUpdated }}</div></div><div class="dashboard-filters"><el-select v-model="filters.regionCode" clearable filterable placeholder="全部区域" @change="loadDashboard"><el-option v-for="region in regionOptions" :key="region.region_code" :label="`${region.name} · ${region.region_code}`" :value="region.region_code" /></el-select><el-select v-model="filters.days" @change="loadDashboard"><el-option label="近 7 日" :value="7" /><el-option label="近 30 日" :value="30" /><el-option label="近 90 日" :value="90" /></el-select><el-button :loading="loading" @click="loadDashboard">刷新驾驶舱</el-button></div></div>
    <el-alert v-if="errorMessage" class="page-alert" type="error" :closable="false" show-icon :title="errorMessage"><template #default><span v-if="traceId">trace_id: {{ traceId }}</span><el-button text type="primary" @click="loadDashboard">重试</el-button></template></el-alert>
    <div class="metric-grid dashboard-metric-grid"><el-card class="metric-card metric-card--blue"><span>站点总数</span><strong>{{ stationTotal.toLocaleString() }}</strong><small>{{ filters.regionCode || '全域' }} · 目录可见站点</small></el-card><el-card class="metric-card metric-card--teal"><span>连接器总数</span><strong>{{ connectorTotal.toLocaleString() }}</strong><small>当前数据源汇总</small></el-card><el-card class="metric-card metric-card--cyan"><span>快充占比</span><strong>{{ fastConnectorRatio }}%</strong><small>DC / FAST / CCS 类型</small></el-card><el-card class="metric-card metric-card--amber"><span>高风险站点</span><strong>{{ highRiskStations.size.toLocaleString() }}</strong><small>高利用率或未恢复故障</small></el-card><el-card class="metric-card metric-card--violet"><span>候选站点</span><strong>{{ candidatesTotal.toLocaleString() }}</strong><small>{{ filters.regionCode || '全域' }} · 候选目录</small></el-card><el-card class="metric-card metric-card--rose"><span>待确认方案</span><strong>{{ pendingConfirmationCount }}</strong><small>报告或运行等待人工确认</small></el-card></div>
    <div class="dashboard-chart-grid dashboard-chart-grid--top"><EChartCard title="充电站地图" subtitle="按经纬度展示站点和运营商图例，点击点位查看详情" tag="站点空间分布" :option="mapOption" :loading="loading" :empty="chartEmpty('map', points)" :error="chartErrors.map" @chart-click="handleChartClick" /><EChartCard title="区域覆盖缺口热力图" subtitle="按区域站点数量计算相对缺口指数" tag="区域覆盖" :option="coverageOption" :loading="loading" :empty="chartEmpty('regions', regions)" :error="chartErrors.regions" @chart-click="handleChartClick" /></div>
    <div class="dashboard-chart-grid dashboard-chart-grid--split"><EChartCard title="运营商站点排行" subtitle="点击运营商跳转到站点目录" tag="运营商" :option="operatorOption" :loading="loading" :empty="chartEmpty('operators', operators)" :error="chartErrors.operators" @chart-click="handleChartClick" /><EChartCard title="充电类型排行" subtitle="按当前加载站点的充电类型统计" tag="充电类型" :option="chargingTypeOption" :loading="loading" :empty="chartEmpty('stations', stations)" :error="chartErrors.stations" @chart-click="handleChartClick" /><EChartCard title="站点运营趋势" subtitle="会话、能耗和平均利用率" tag="运营指标" :option="trendOption" :loading="loading" :empty="chartEmpty('trend', metrics)" :error="chartErrors.trend" @chart-click="handleChartClick" /></div>
    <div class="dashboard-chart-grid dashboard-chart-grid--split"><EChartCard title="故障和恢复时间线" subtitle="按故障发生日期汇总故障与恢复数量" tag="故障" :option="faultOption" :loading="loading" :empty="chartEmpty('faults', faults)" :error="chartErrors.faults" @chart-click="handleChartClick" /><EChartCard title="候选站点评分雷达" subtitle="完整度、交通、人口、电力和数据时效" tag="候选评分" :option="candidateRadarOption" :loading="loading" :empty="chartEmpty('candidates', candidates)" :error="chartErrors.candidates" @chart-click="handleChartClick" /><EChartCard title="竞争强度与候选评分" subtitle="交通/人口指标与数据完整度散点分布" tag="竞争分析" :option="competitionOption" :loading="loading" :empty="chartEmpty('candidates', candidates)" :error="chartErrors.candidates" @chart-click="handleChartClick" /></div>
    <div class="dashboard-bottom-grid"><el-card class="dashboard-list-card"><template #header><div class="card-header"><div><strong>扩容优先级</strong><small>基于利用率和故障风险的确定性排序</small></div><el-tag type="warning" effect="plain">{{ expansionPriorities.length }}</el-tag></div></template><el-empty v-if="!expansionPriorities.length && !loading" description="暂无扩容风险数据" :image-size="52" /><div v-else class="priority-list"><button v-for="item in expansionPriorities" :key="item.stationId" type="button" class="priority-item" @click="openStation(item.stationId)"><span class="priority-rank">{{ item.score }}</span><span class="priority-copy"><strong>{{ item.station?.station_name || `站点 #${item.stationId}` }}</strong><small>{{ item.station?.operator?.operator_name || '未标注运营商' }} · {{ item.station?.region?.name || '未标注区域' }}</small></span><el-tag size="small" :type="item.score >= 70 ? 'danger' : 'warning'">{{ item.score >= 70 ? '高优先级' : '关注' }}</el-tag></button></div></el-card><el-card class="dashboard-list-card"><template #header><div class="card-header"><div><strong>最近 Agent 运行</strong><small>点击卡片进入对应分析工作台</small></div><el-link type="primary" @click="router.push('/runs')">查看全部</el-link></div></template><el-empty v-if="!runs.length && !loading" description="暂无运行记录" :image-size="52" /><div v-else class="run-list"><button v-for="run in runs.slice(0, 6)" :key="run.run_id" type="button" class="run-item" @click="router.push(`/agents/${run.agent_type === 'site_selection' ? 'site-selection' : run.agent_type === 'policy_matching' ? 'policy' : run.agent_type === 'coverage_gap' ? 'coverage' : run.agent_type}`)"><span class="activity-indicator" :class="`activity-indicator--${run.status === 'COMPLETED' ? 'success' : 'warning'}`" /><span><strong>{{ ({ coverage_gap: '覆盖缺口', competition: '竞争分析', site_selection: '候选选址', expansion: '站点扩容', policy_matching: '政策匹配' } as Record<string, string>)[run.agent_type] || run.agent_type }}</strong><small>{{ run.status }} · {{ new Date(run.created_at).toLocaleString('zh-CN', { hour12: false }) }}</small></span><el-icon><ArrowRight /></el-icon></button></div></el-card></div>
  </section>
</template>
