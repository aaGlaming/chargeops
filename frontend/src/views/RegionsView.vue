<script setup lang="ts">
import { computed, onMounted, shallowRef } from 'vue'
import { getApiError } from '../api/http'
import { getRegion, listRegions, listStations, type RegionSummary, type Station } from '../api/catalog'

const regions = shallowRef<RegionSummary[]>([])
const selectedRegion = shallowRef<(RegionSummary & { child_regions?: RegionSummary[] }) | null>(null)
const regionStations = shallowRef<Station[]>([])
const loading = shallowRef(false)
const detailLoading = shallowRef(false)
const errorMessage = shallowRef('')
const traceId = shallowRef('')
const selectedCode = shallowRef('')

const regionStats = computed(() => {
  const stationCount = regionStations.value.length
  const connectorCount = regionStations.value.reduce((sum, station) => sum + station.total_connector_count, 0)
  const withCoordinates = regionStations.value.filter((station) => station.latitude != null && station.longitude != null).length
  const active = regionStations.value.filter((station) => station.station_status.toUpperCase().includes('E')).length
  return { stationCount, connectorCount, withCoordinates, active, density: stationCount ? (connectorCount / stationCount).toFixed(1) : '0.0', coordinateRate: stationCount ? Math.round(withCoordinates / stationCount * 100) : 0 }
})

async function loadRegions() {
  loading.value = true
  errorMessage.value = ''
  try {
    regions.value = (await listRegions({ page: 1, page_size: 200 })).items
    if (!selectedCode.value && regions.value[0]) await selectRegion(regions.value[0].region_code)
  } catch (error) {
    const detail = getApiError(error)
    errorMessage.value = detail.message
    traceId.value = detail.traceId
  } finally {
    loading.value = false
  }
}

async function selectRegion(code: string) {
  selectedCode.value = code
  detailLoading.value = true
  try {
    const [detail, stationResponse] = await Promise.all([getRegion(code), listStations({ region_code: code, page: 1, page_size: 200 })])
    selectedRegion.value = detail
    regionStations.value = stationResponse.items
  } catch (error) {
    errorMessage.value = getApiError(error).message
  } finally {
    detailLoading.value = false
  }
}

function sourceLabel(value: string) {
  return ({ public: '公开', user_upload: '上传', synthetic: '合成', agent: 'Agent' } as Record<string, string>)[value] || value
}

onMounted(loadRegions)
</script>

<template>
  <section class="regions-page">
    <div class="page-toolbar station-toolbar"><div class="data-freshness"><span class="status-dot" /> 区域分析基于当前可见站点数据</div><el-button :loading="loading" @click="loadRegions">刷新区域</el-button></div>
    <el-alert v-if="errorMessage" class="page-alert" type="error" :closable="false" show-icon :title="errorMessage"><template #default><span v-if="traceId">trace_id: {{ traceId }}</span><el-button text type="primary" @click="loadRegions">重试</el-button></template></el-alert>
    <div class="region-layout">
      <el-card class="region-list-card"><template #header><div class="card-header"><div><strong>区域目录</strong><small>选择区域查看覆盖摘要</small></div><el-tag type="info" effect="plain">{{ regions.length }}</el-tag></div></template><el-table v-loading="loading" :data="regions" size="small" height="580" highlight-current-row @row-click="(row: RegionSummary) => selectRegion(row.region_code)"><el-table-column prop="name" label="区域" min-width="150"><template #default="scope"><div class="station-name-cell"><strong>{{ scope.row.name }}</strong><small>{{ scope.row.region_code }}</small></div></template></el-table-column><el-table-column prop="region_type" label="层级" width="84" /><el-table-column prop="station_count" label="站点数" width="82" /><el-table-column label="来源" width="75"><template #default="scope"><el-tag size="small" effect="plain">{{ sourceLabel(scope.row.source.source_type) }}</el-tag></template></el-table-column></el-table></el-card>
      <div class="region-detail-column">
        <el-card v-loading="detailLoading" class="region-summary-card"><template #header><div class="card-header"><div><strong>{{ selectedRegion?.name || '区域分析' }}</strong><small>{{ selectedRegion?.region_code || '请选择左侧区域' }}</small></div><el-tag v-if="selectedRegion" type="success" effect="plain">已选区域</el-tag></div></template><div v-if="selectedRegion" class="metric-grid metric-grid--compact"><div class="mini-metric"><span>站点数量</span><strong>{{ regionStats.stationCount }}</strong><small>目录可见站点</small></div><div class="mini-metric"><span>连接器数量</span><strong>{{ regionStats.connectorCount }}</strong><small>站点总连接器</small></div><div class="mini-metric"><span>平均连接器</span><strong>{{ regionStats.density }}</strong><small>每站点平均</small></div><div class="mini-metric"><span>坐标完整率</span><strong>{{ regionStats.coordinateRate }}%</strong><small>{{ regionStats.withCoordinates }} 个有坐标</small></div></div><el-empty v-else description="请选择区域" :image-size="65" /></el-card>
        <el-card class="coverage-summary-card"><template #header><div class="card-header"><div><strong>覆盖缺口摘要</strong><small>根据站点状态、坐标和连接器配置生成</small></div><el-tag type="warning" effect="plain">确定性摘要</el-tag></div></template><div v-if="selectedRegion" class="coverage-bars"><div class="coverage-bar-row"><div><span>运营站点</span><strong>{{ regionStats.active }} / {{ regionStats.stationCount }}</strong></div><el-progress :percentage="regionStats.stationCount ? Math.round(regionStats.active / regionStats.stationCount * 100) : 0" :show-text="false" status="success" /></div><div class="coverage-bar-row"><div><span>坐标完整</span><strong>{{ regionStats.coordinateRate }}%</strong></div><el-progress :percentage="regionStats.coordinateRate" :show-text="false" /></div><div class="coverage-gap-callout"><span class="status-dot" :class="{ 'status-dot--warning': regionStats.coordinateRate < 95 }" /><div><strong>{{ regionStats.coordinateRate < 95 ? '存在位置数据缺口' : '位置数据完整' }}</strong><small>{{ regionStats.coordinateRate < 95 ? '建议先补齐站点坐标，再运行覆盖缺口 Agent。' : '当前区域具备运行空间覆盖分析的基础数据。' }}</small></div></div></div><el-empty v-else description="暂无区域摘要" :image-size="58" /></el-card>
        <el-card class="children-card"><template #header><div class="card-header"><div><strong>下级区域</strong><small>当前区域层级关系</small></div></div></template><el-empty v-if="!selectedRegion?.child_regions?.length" description="暂无下级区域" :image-size="52" /><div v-else class="child-region-list"><el-tag v-for="child in selectedRegion.child_regions" :key="child.region_code" effect="plain">{{ child.name }} · {{ child.station_count }} 站</el-tag></div></el-card>
      </div>
    </div>
  </section>
</template>

