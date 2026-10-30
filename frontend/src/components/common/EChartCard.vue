<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, HeatmapChart, LineChart, PieChart, RadarChart, ScatterChart } from 'echarts/charts'
import { DatasetComponent, GridComponent, LegendComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsOption } from 'echarts'

echarts.use([BarChart, HeatmapChart, LineChart, PieChart, RadarChart, ScatterChart, DatasetComponent, GridComponent, LegendComponent, TooltipComponent, VisualMapComponent, CanvasRenderer])

const props = withDefaults(defineProps<{ title: string; subtitle?: string; option?: EChartsOption; loading?: boolean; empty?: boolean; error?: string; height?: number; tag?: string }>(), { subtitle: '', option: undefined, loading: false, empty: false, error: '', height: 292, tag: '数据' })
const emit = defineEmits<{ chartClick: [payload: unknown] }>()
const canvas = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | undefined
let resizeObserver: ResizeObserver | undefined

function disposeChart() {
  chart?.dispose()
  chart = undefined
}

function render() {
  if (!canvas.value || props.empty || props.error || !props.option) {
    disposeChart()
    return
  }
  chart ||= echarts.init(canvas.value)
  chart.setOption(props.option, true)
  chart.off('click')
  chart.on('click', (params) => emit('chartClick', params))
}

watch(() => [props.option, props.empty, props.error], () => nextTick(render), { deep: true })
onMounted(() => {
  render()
  if (canvas.value) {
    resizeObserver = new ResizeObserver(() => chart?.resize())
    resizeObserver.observe(canvas.value)
  }
})
onBeforeUnmount(() => { resizeObserver?.disconnect(); disposeChart() })
</script>

<template>
  <el-card class="dashboard-chart-card" :class="{ 'dashboard-chart-card--wide': height > 320 }">
    <template #header><div class="card-header"><div><strong>{{ title }}</strong><small>{{ subtitle }}</small></div><el-tag type="info" effect="plain">{{ tag }}</el-tag></div></template>
    <div v-if="error" class="chart-state"><el-result icon="error" title="图表加载失败" :sub-title="error"><template #extra><el-button type="primary" plain @click="$emit('chartClick', { action: 'retry' })">重试</el-button></template></el-result></div>
    <div v-else-if="empty" class="chart-state"><el-empty description="暂无可展示的数据" :image-size="64" /></div>
    <div v-else ref="canvas" v-loading="loading" class="dashboard-chart-canvas" :style="{ height: `${height}px` }" />
  </el-card>
</template>
