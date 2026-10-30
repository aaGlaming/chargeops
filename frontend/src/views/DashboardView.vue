<script setup lang="ts">
import { shallowRef } from 'vue'
import { ElMessage } from 'element-plus'
import ChartCard from '../components/common/ChartCard.vue'

const loading = shallowRef(false)
const showEmptyState = shallowRef(false)

function refresh() {
  loading.value = true
  window.setTimeout(() => {
    loading.value = false
    ElMessage.success('驾驶舱数据已刷新。')
  }, 450)
}
</script>

<template>
  <section class="dashboard-page">
    <div class="page-toolbar">
      <span class="data-freshness"><span class="status-dot" /> 数据更新时间：刚刚</span>
      <el-button :loading="loading" @click="refresh">刷新数据</el-button>
    </div>
    <div class="metric-grid">
      <el-card v-for="metric in [
        { label: '运营站点', value: '20,355', note: '+3.2% 较上期', tone: 'blue' },
        { label: '活跃连接器', value: '20,677', note: '公开数据快照', tone: 'teal' },
        { label: '待处理运行', value: '08', note: '2 个需要确认', tone: 'amber' },
        { label: '知识库文档', value: '24', note: 'RAG 已索引', tone: 'violet' },
      ]" :key="metric.label" class="metric-card" :class="`metric-card--${metric.tone}`">
        <span>{{ metric.label }}</span>
        <strong>{{ metric.value }}</strong>
        <small>{{ metric.note }}</small>
      </el-card>
    </div>
    <div class="dashboard-grid">
      <ChartCard title="区域覆盖概览" subtitle="近 30 日站点覆盖与需求变化" :loading="loading" :empty="showEmptyState" />
      <el-card class="activity-card">
        <template #header><div class="card-header"><span>最近运行</span><el-link type="primary" href="#/runs">查看全部</el-link></div></template>
        <div class="activity-list">
          <div v-for="item in [
            { title: '政策与补贴匹配', status: '已完成', time: '10 分钟前', type: 'success' },
            { title: '站点扩容规划', status: '待确认', time: '26 分钟前', type: 'warning' },
            { title: '区域覆盖缺口', status: '已完成', time: '1 小时前', type: 'success' },
          ]" :key="item.title" class="activity-item">
            <div><span class="activity-indicator" :class="`activity-indicator--${item.type}`" /><strong>{{ item.title }}</strong></div>
            <div><el-tag size="small" :type="item.type === 'success' ? 'success' : 'warning'">{{ item.status }}</el-tag><small>{{ item.time }}</small></div>
          </div>
        </div>
      </el-card>
    </div>
  </section>
</template>

