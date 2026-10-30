<script setup lang="ts">
import { computed, onMounted, reactive, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Location } from '@element-plus/icons-vue'
import StationMap from '../components/common/StationMap.vue'
import { getApiError } from '../api/http'
import { getRegion, getStation, listOperators, listRegions, listStationConnectors, listStationMapPoints, listStations, type Connector, type MapPoint, type OperatorSummary, type RegionSummary, type Station, type StationDetail } from '../api/catalog'
import { listFaults, listMetrics, type Fault, type Metric } from '../api/operations'

const route = useRoute()
const router = useRouter()
const filters = reactive({ regionCode: '', operatorId: '', chargingType: '', stationStatus: '', accessType: '', sourceType: '' })
const regions = shallowRef<RegionSummary[]>([])
const operators = shallowRef<OperatorSummary[]>([])
const stations = shallowRef<Station[]>([])
const points = shallowRef<MapPoint[]>([])
const loading = shallowRef(false)
const errorMessage = shallowRef('')
const traceId = shallowRef('')
const page = shallowRef(1)
const pageSize = shallowRef(25)
const total = shallowRef(0)
const sortKey = shallowRef<'station_name' | 'total_connector_count' | 'station_status'>('station_name')
const sortOrder = shallowRef<'ascending' | 'descending' | null>(null)
const selectedStationId = shallowRef<number | null>(null)
const drawerVisible = shallowRef(false)
const detailLoading = shallowRef(false)
const detailError = shallowRef('')
const stationDetail = shallowRef<StationDetail | null>(null)
const connectors = shallowRef<Connector[]>([])
const metrics = shallowRef<Metric[]>([])
const faults = shallowRef<Fault[]>([])

const sortedStations = computed(() => {
  if (!sortOrder.value) return stations.value
  return [...stations.value].sort((left, right) => {
    const a = String(left[sortKey.value] ?? '')
    const b = String(right[sortKey.value] ?? '')
    const result = sortKey.value === 'total_connector_count' ? Number(a) - Number(b) : a.localeCompare(b)
    return sortOrder.value === 'ascending' ? result : -result
  })
})

function sourceLabel(value: string) {
  return ({ public: '公开', user_upload: '上传', synthetic: '合成', agent: 'Agent' } as Record<string, string>)[value] || value
}

function statusType(status: string) {
  const value = status.toUpperCase()
  if (value.includes('E') || value.includes('OPEN') || value.includes('ACTIVE')) return 'success'
  if (value.includes('P') || value.includes('PLANNED')) return 'warning'
  return 'info'
}

async function loadCatalogOptions() {
  try {
    const [regionResponse, operatorResponse] = await Promise.all([listRegions({ page: 1, page_size: 200 }), listOperators({ page: 1, page_size: 200 })])
    regions.value = regionResponse.items
    operators.value = operatorResponse.items
  } catch {
    // The main table keeps its own error state; filter options can remain empty.
  }
}

async function loadStations() {
  loading.value = true
  errorMessage.value = ''
  traceId.value = ''
  const params = { region_code: filters.regionCode || undefined, operator_id: filters.operatorId ? Number(filters.operatorId) : undefined, charging_type: filters.chargingType || undefined, station_status: filters.stationStatus || undefined, access_type: filters.accessType || undefined, source_type: filters.sourceType || undefined, page: page.value, page_size: pageSize.value }
  try {
    const [stationResponse, pointResponse] = await Promise.all([listStations(params), listStationMapPoints(params)])
    stations.value = stationResponse.items
    total.value = stationResponse.page.total
    points.value = pointResponse.items
  } catch (error) {
    const detail = getApiError(error)
    errorMessage.value = detail.message
    traceId.value = detail.traceId
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  Object.assign(filters, { regionCode: '', operatorId: '', chargingType: '', stationStatus: '', accessType: '', sourceType: '' })
  page.value = 1
  loadStations()
}

function handleSort({ prop, order }: { prop: string; order: 'ascending' | 'descending' | null }) {
  if (prop === 'station_name' || prop === 'total_connector_count' || prop === 'station_status') sortKey.value = prop
  sortOrder.value = order
}

function openStation(stationId: number) {
  selectedStationId.value = stationId
  drawerVisible.value = true
  router.replace({ name: 'stations', query: { station_id: String(stationId) } })
  loadStationDetail(stationId)
}

async function loadStationDetail(stationId: number) {
  detailLoading.value = true
  detailError.value = ''
  try {
    const [detail, connectorResponse, metricResponse, faultResponse] = await Promise.all([getStation(stationId), listStationConnectors(stationId), listMetrics(stationId), listFaults(stationId)])
    stationDetail.value = detail
    connectors.value = connectorResponse.items
    metrics.value = metricResponse.items
    faults.value = faultResponse.items
  } catch (error) {
    detailError.value = getApiError(error).message
  } finally {
    detailLoading.value = false
  }
}

function closeDrawer() {
  drawerVisible.value = false
  selectedStationId.value = null
  router.replace({ name: 'stations' })
}

function handlePageChange(value: number) {
  page.value = value
  loadStations()
}

watch(() => [filters.regionCode, filters.operatorId, filters.chargingType, filters.stationStatus, filters.accessType, filters.sourceType], () => { page.value = 1; loadStations() })
watch(() => route.query.station_id, (value) => {
  const id = Number(value)
  if (Number.isFinite(id) && id > 0) {
    selectedStationId.value = id
    drawerVisible.value = true
    loadStationDetail(id)
  }
}, { immediate: true })
onMounted(() => { loadCatalogOptions(); loadStations() })
</script>

<template>
  <section class="stations-page">
    <div class="page-toolbar station-toolbar"><div class="data-freshness"><span class="status-dot" /> 当前展示 {{ total.toLocaleString() }} 个站点</div><el-button @click="loadStations">刷新数据</el-button></div>
    <el-card class="filter-card">
      <div class="filter-grid">
        <el-form-item label="区域"><el-select v-model="filters.regionCode" clearable filterable placeholder="全部区域"><el-option v-for="region in regions" :key="region.region_code" :label="`${region.name} · ${region.region_code}`" :value="region.region_code" /></el-select></el-form-item>
        <el-form-item label="运营商"><el-select v-model="filters.operatorId" clearable filterable placeholder="全部运营商"><el-option v-for="operator in operators" :key="operator.id" :label="operator.operator_name" :value="String(operator.id)" /></el-select></el-form-item>
        <el-form-item label="充电类型"><el-select v-model="filters.chargingType" clearable placeholder="全部类型"><el-option label="直流快充" value="DC_FAST" /><el-option label="交流慢充" value="LEVEL_2" /><el-option label="CHAdeMO" value="CHADEMO" /><el-option label="J1772" value="J1772" /></el-select></el-form-item>
        <el-form-item label="站点状态"><el-select v-model="filters.stationStatus" clearable placeholder="全部状态"><el-option label="运营中" value="E" /><el-option label="规划中" value="P" /><el-option label="暂不可用" value="T" /></el-select></el-form-item>
        <el-form-item label="来源"><el-select v-model="filters.sourceType" clearable placeholder="全部来源"><el-option label="公开数据" value="public" /><el-option label="用户上传" value="user_upload" /><el-option label="合成数据" value="synthetic" /></el-select></el-form-item>
        <el-form-item label="访问类型"><el-select v-model="filters.accessType" clearable placeholder="全部访问类型"><el-option label="公众可用" value="PUBLIC" /><el-option label="私人" value="PRIVATE" /></el-select></el-form-item>
        <el-button class="filter-reset" text @click="resetFilters">重置筛选</el-button>
      </div>
    </el-card>
    <el-alert v-if="errorMessage" class="page-alert" type="error" :closable="false" show-icon :title="errorMessage"><template #default><span v-if="traceId">trace_id: {{ traceId }}</span><el-button text type="primary" @click="loadStations">重试</el-button></template></el-alert>
    <div class="station-content-grid">
      <el-card class="map-card"><template #header><div class="card-header"><div><strong>充电站地图</strong><small>按经纬度展示当前筛选结果</small></div><el-tag type="info" effect="plain">{{ points.length }} 个点位</el-tag></div></template><StationMap :points="points" :selected-id="selectedStationId" :loading="loading" @select="openStation" /></el-card>
      <el-card class="station-table-card"><template #header><div class="card-header"><div><strong>站点列表</strong><small>点击行查看站点详情</small></div><el-tag type="info" effect="plain">{{ total.toLocaleString() }} 条</el-tag></div></template>
        <el-table v-loading="loading" :data="sortedStations" size="small" height="420" empty-text="暂无符合筛选条件的站点" @row-click="(row: Station) => openStation(row.id)" @sort-change="handleSort">
          <el-table-column prop="station_name" label="站点" min-width="188" sortable="custom"><template #default="scope"><div class="station-name-cell"><strong>{{ scope.row.station_name }}</strong><small>{{ scope.row.city || '未知城市' }} · {{ scope.row.external_station_id }}</small></div></template></el-table-column>
          <el-table-column label="运营商" min-width="110"><template #default="scope">{{ scope.row.operator?.operator_name || '未关联' }}</template></el-table-column>
          <el-table-column prop="total_connector_count" label="连接器" width="86" sortable="custom" />
          <el-table-column prop="station_status" label="状态" width="84" sortable="custom"><template #default="scope"><el-tag size="small" :type="statusType(scope.row.station_status)">{{ scope.row.station_status }}</el-tag></template></el-table-column>
          <el-table-column label="来源" width="76"><template #default="scope"><el-tag size="small" effect="plain">{{ sourceLabel(scope.row.source.source_type) }}</el-tag></template></el-table-column>
        </el-table>
        <div class="table-pagination"><el-pagination v-model:current-page="page" v-model:page-size="pageSize" background layout="prev, pager, next" :total="total" :page-sizes="[25]" @current-change="handlePageChange" /></div>
      </el-card>
    </div>

    <el-drawer :model-value="drawerVisible" title="站点详情" size="560px" @close="closeDrawer">
      <div v-loading="detailLoading" class="station-detail-drawer">
        <el-alert v-if="detailError" type="error" :closable="false" show-icon :title="detailError"><el-button text type="primary" @click="selectedStationId && loadStationDetail(selectedStationId)">重试</el-button></el-alert>
        <template v-if="stationDetail">
          <div class="detail-hero"><div class="workspace-icon"><el-icon><Location /></el-icon></div><div><span class="eyebrow">{{ stationDetail.external_station_id }}</span><h2>{{ stationDetail.station_name }}</h2><p>{{ stationDetail.street_address || '地址未登记' }} · {{ stationDetail.city || '未知城市' }}</p></div><el-tag :type="statusType(stationDetail.station_status)">{{ stationDetail.station_status }}</el-tag></div>
          <el-descriptions :column="2" border size="small"><el-descriptions-item label="运营商">{{ stationDetail.operator?.operator_name || '未关联' }}</el-descriptions-item><el-descriptions-item label="区域">{{ stationDetail.region?.name || '未关联' }}</el-descriptions-item><el-descriptions-item label="访问类型">{{ stationDetail.access_type }}</el-descriptions-item><el-descriptions-item label="连接器总数">{{ stationDetail.total_connector_count }}</el-descriptions-item><el-descriptions-item label="经纬度">{{ stationDetail.latitude ?? '-' }}, {{ stationDetail.longitude ?? '-' }}</el-descriptions-item><el-descriptions-item label="数据来源">{{ sourceLabel(stationDetail.source.source_type) }}</el-descriptions-item></el-descriptions>
          <el-tabs class="detail-tabs"><el-tab-pane label="连接器"><el-empty v-if="!connectors.length" description="暂无连接器记录" :image-size="52" /><el-table v-else :data="connectors" size="small"><el-table-column prop="connector_type" label="类型" /><el-table-column prop="quantity" label="数量" width="70" /><el-table-column prop="power_kw" label="功率 kW" width="92" /><el-table-column prop="connector_status" label="状态" /></el-table></el-tab-pane><el-tab-pane label="运营指标"><el-empty v-if="!metrics.length" description="暂无运营指标" :image-size="52" /><el-table v-else :data="metrics" size="small"><el-table-column prop="metric_date" label="日期" width="100" /><el-table-column prop="charging_sessions" label="会话数" /><el-table-column prop="energy_kwh" label="能耗 kWh" /><el-table-column prop="occupancy_rate" label="利用率" /></el-table></el-tab-pane><el-tab-pane label="故障"><el-empty v-if="!faults.length" description="暂无故障记录" :image-size="52" /><el-table v-else :data="faults" size="small"><el-table-column prop="fault_type" label="类型" /><el-table-column prop="severity" label="等级" /><el-table-column prop="status" label="状态" /><el-table-column prop="started_at" label="开始时间" /></el-table></el-tab-pane><el-tab-pane label="关联结果"><div class="related-results"><div><strong>Agent 运行</strong><span>{{ stationDetail.related.agent_runs ?? 0 }}</span></div><div><strong>扩容方案</strong><span>{{ stationDetail.related.expansion_plans ?? 0 }}</span></div><div><strong>站点评分</strong><span>{{ stationDetail.related.site_scores ?? 0 }}</span></div></div></el-tab-pane></el-tabs>
        </template>
      </div>
    </el-drawer>
  </section>
</template>

