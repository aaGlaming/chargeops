<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { MapPoint } from '../../api/catalog'

echarts.use([ScatterChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = withDefaults(defineProps<{ points: MapPoint[]; selectedId?: number | null; loading?: boolean }>(), { selectedId: null, loading: false })
const emit = defineEmits<{ select: [stationId: number] }>()
const canvas = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | undefined
let resizeObserver: ResizeObserver | undefined

function colorForStatus(status: string) {
  const normalized = status.toUpperCase()
  if (normalized.includes('E') || normalized.includes('OPEN') || normalized.includes('ACTIVE')) return '#36b37e'
  if (normalized.includes('P') || normalized.includes('PLANNED')) return '#e2a33c'
  return '#8b9ab4'
}

function render() {
  if (!canvas.value) return
  chart ||= echarts.init(canvas.value)
  const points = props.points.filter((point) => Number.isFinite(point.longitude) && Number.isFinite(point.latitude)).map((point) => ({
    value: [point.longitude, point.latitude, point.id],
    name: point.station_name,
    stationId: point.id,
    itemStyle: { color: point.id === props.selectedId ? '#3157dd' : colorForStatus(point.station_status), borderColor: point.id === props.selectedId ? '#fff' : 'transparent', borderWidth: point.id === props.selectedId ? 2 : 0 },
  }))
  chart.setOption({
    animation: false,
    grid: { left: 58, right: 22, top: 24, bottom: 42 },
    tooltip: { trigger: 'item', formatter: (params: { data?: { name?: string; value?: number[] } }) => `${params.data?.name || '站点'}<br/>经度 ${params.data?.value?.[0] ?? '-'} · 纬度 ${params.data?.value?.[1] ?? '-'}` },
    xAxis: { type: 'value', name: '经度', nameLocation: 'middle', nameGap: 28, scale: true, splitLine: { lineStyle: { color: '#eef1f5' } }, axisLabel: { color: '#8b98aa', fontSize: 10 } },
    yAxis: { type: 'value', name: '纬度', nameLocation: 'middle', nameGap: 42, scale: true, splitLine: { lineStyle: { color: '#eef1f5' } }, axisLabel: { color: '#8b98aa', fontSize: 10 } },
    series: [{ type: 'scatter', symbolSize: (value: number[]) => Math.max(7, Math.min(18, 6 + Math.sqrt(Number(value[2]) % 12))), data: points }],
  }, true)
  chart.off('click')
  chart.on('click', (params: any) => {
    if (params.data?.stationId) emit('select', params.data.stationId)
  })
}

onMounted(() => {
  render()
  if (canvas.value) {
    resizeObserver = new ResizeObserver(() => chart?.resize())
    resizeObserver.observe(canvas.value)
  }
})
watch(() => [props.points, props.selectedId], render, { deep: true })
onBeforeUnmount(() => { resizeObserver?.disconnect(); chart?.dispose() })
</script>

<template>
  <div v-loading="loading" class="station-map-shell">
    <div ref="canvas" class="station-map-canvas" aria-label="充电站经纬度地图" />
    <div class="map-legend"><span><i class="legend-dot legend-dot--active" />运营中</span><span><i class="legend-dot legend-dot--planned" />规划中</span><span><i class="legend-dot legend-dot--unknown" />其他</span><small>点击点位查看详情</small></div>
  </div>
</template>

