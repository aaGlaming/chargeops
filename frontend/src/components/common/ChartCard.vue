<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const props = withDefaults(defineProps<{ title: string; subtitle?: string; loading?: boolean; empty?: boolean }>(), { loading: false, empty: false })
const chartElement = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | undefined
let resizeObserver: ResizeObserver | undefined

function renderChart() {
  if (!chartElement.value || props.empty) return
  chart ||= echarts.init(chartElement.value)
  chart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 36, right: 18, top: 22, bottom: 28 },
    xAxis: { type: 'category', boundaryGap: false, data: ['10/01', '10/06', '10/11', '10/16', '10/21', '10/26', '10/30'] },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#eef1f5' } } },
    series: [{ name: '覆盖站点', type: 'line', smooth: true, data: [52, 56, 55, 63, 68, 71, 76], showSymbol: false, lineStyle: { color: '#3563e9', width: 3 }, areaStyle: { color: 'rgba(53, 99, 233, .10)' } }],
  })
}

onMounted(() => {
  renderChart()
  if (chartElement.value) {
    resizeObserver = new ResizeObserver(() => chart?.resize())
    resizeObserver.observe(chartElement.value)
  }
})
watch(() => props.empty, renderChart)
onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  chart?.dispose()
})
</script>

<template>
  <el-card class="chart-card" v-loading="loading">
    <template #header><div class="card-header"><div><strong>{{ title }}</strong><small>{{ subtitle }}</small></div><el-tag type="info" effect="plain">近 30 日</el-tag></div></template>
    <div v-if="empty" class="state-panel"><el-empty description="暂无可展示的数据" /></div>
    <div v-else ref="chartElement" class="chart-canvas" aria-label="区域覆盖趋势图" />
  </el-card>
</template>

