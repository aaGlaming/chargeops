<script setup lang="ts">
import { computed, onMounted, reactive, shallowRef } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, View } from '@element-plus/icons-vue'
import { getApiError } from '../api/http'
import { getAgentRun, listAgentRuns, type AgentRun, type AgentRunSummary } from '../api/agents'

const filters = reactive({ agentType: '', status: '' })
const runs = shallowRef<AgentRunSummary[]>([])
const selectedRun = shallowRef<AgentRun | null>(null)
const drawerVisible = shallowRef(false)
const loading = shallowRef(false)
const detailLoading = shallowRef(false)
const errorMessage = shallowRef('')
const traceId = shallowRef('')
const filteredRuns = computed(() => runs.value.filter((run) => (!filters.agentType || run.agent_type === filters.agentType) && (!filters.status || run.status === filters.status)))

function typeLabel(value: string) { return ({ coverage_gap: '覆盖缺口', competition: '竞争分析', site_selection: '候选选址', expansion: '站点扩容', policy_matching: '政策匹配' } as Record<string, string>)[value] || value }
function statusType(value: string) { return value === 'COMPLETED' ? 'success' : ['FAILED', 'BLOCKED', 'CANCELLED'].includes(value) ? 'danger' : value === 'WAITING_CONFIRMATION' ? 'warning' : 'info' }
function formatTime(value?: string | null) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-' }

async function loadRuns() {
  loading.value = true; errorMessage.value = ''; traceId.value = ''
  try { runs.value = (await listAgentRuns()).items } catch (error) { const detail = getApiError(error); errorMessage.value = detail.message; traceId.value = detail.traceId } finally { loading.value = false }
}

async function openRun(runId: string) {
  drawerVisible.value = true; detailLoading.value = true; selectedRun.value = null
  try { selectedRun.value = await getAgentRun(runId) } catch (error) { ElMessage.error(getApiError(error).message) } finally { detailLoading.value = false }
}

onMounted(loadRuns)
</script>

<template>
  <section class="observability-page">
    <div class="observability-toolbar"><div><span class="eyebrow">AGENT EXECUTION / TRACE</span><h2>Agent 运行记录</h2><p>查看运行状态、停止原因、模型事件和工具调用轨迹。</p></div><el-button :loading="loading" @click="loadRuns"><el-icon><Refresh /></el-icon>刷新</el-button></div>
    <el-alert v-if="errorMessage" class="page-alert" type="error" :closable="false" show-icon :title="errorMessage"><template #default><span v-if="traceId">trace_id: {{ traceId }}</span><el-button text type="primary" @click="loadRuns">重试</el-button></template></el-alert>
    <el-card class="observability-card"><div class="observability-filter-row"><el-select v-model="filters.agentType" clearable placeholder="Agent 类型"><el-option label="覆盖缺口" value="coverage_gap" /><el-option label="竞争分析" value="competition" /><el-option label="候选选址" value="site_selection" /><el-option label="站点扩容" value="expansion" /><el-option label="政策匹配" value="policy_matching" /></el-select><el-select v-model="filters.status" clearable placeholder="状态"><el-option label="待运行" value="PENDING" /><el-option label="运行中" value="RUNNING" /><el-option label="待确认" value="WAITING_CONFIRMATION" /><el-option label="已完成" value="COMPLETED" /><el-option label="失败" value="FAILED" /><el-option label="阻塞" value="BLOCKED" /></el-select><el-tag type="info" effect="plain">{{ filteredRuns.length }} 条</el-tag></div><el-table v-loading="loading" :data="filteredRuns" size="small" height="560" empty-text="暂无 Agent 运行记录" @row-click="(row: AgentRunSummary) => openRun(row.run_id)"><el-table-column label="Agent" min-width="150"><template #default="scope"><div class="station-name-cell"><strong>{{ typeLabel(scope.row.agent_type) }}</strong><small>{{ scope.row.run_id }}</small></div></template></el-table-column><el-table-column label="状态" width="130"><template #default="scope"><el-tag size="small" :type="statusType(scope.row.status)">{{ scope.row.status }}</el-tag></template></el-table-column><el-table-column prop="confirmation_status" label="确认" width="120" /><el-table-column label="停止原因" min-width="150"><template #default="scope">{{ scope.row.stop_reason || '-' }}</template></el-table-column><el-table-column label="创建时间" width="170"><template #default="scope">{{ formatTime(scope.row.created_at) }}</template></el-table-column><el-table-column label="查看" width="72"><template #default="scope"><el-button text type="primary" @click.stop="openRun(scope.row.run_id)"><el-icon><View /></el-icon></el-button></template></el-table-column></el-table></el-card>
    <el-drawer v-model="drawerVisible" title="Agent 运行详情" size="650px"><div v-loading="detailLoading" class="run-detail" v-if="selectedRun"><div class="detail-hero"><div class="workspace-icon"><el-icon><View /></el-icon></div><div><span class="eyebrow">{{ selectedRun.run_id }}</span><h2>{{ typeLabel(selectedRun.agent_type) }}</h2><p>{{ selectedRun.stop_reason || '运行轨迹与状态快照' }}</p></div><el-tag :type="statusType(selectedRun.status)">{{ selectedRun.status }}</el-tag></div><el-descriptions :column="2" border size="small"><el-descriptions-item label="确认状态">{{ selectedRun.confirmation_status }}</el-descriptions-item><el-descriptions-item label="请求用户">{{ selectedRun.requested_by }}</el-descriptions-item><el-descriptions-item label="数据版本">{{ selectedRun.data_version || '-' }}</el-descriptions-item><el-descriptions-item label="Prompt 版本">{{ selectedRun.prompt_version || '-' }}</el-descriptions-item><el-descriptions-item label="模型">{{ selectedRun.model_name || '-' }}</el-descriptions-item><el-descriptions-item label="Embedding">{{ selectedRun.embedding_model || '-' }}</el-descriptions-item></el-descriptions><div class="run-detail-section"><div class="subsection-title"><strong>工具轨迹</strong><small>{{ selectedRun.tool_calls.length }} 次</small></div><el-timeline><el-timeline-item v-for="call in selectedRun.tool_calls" :key="call.id" :type="call.status === 'SUCCEEDED' ? 'success' : call.status === 'FAILED' ? 'danger' : 'primary'" :timestamp="formatTime(call.started_at)"><strong>{{ call.tool_name }}</strong><small>{{ call.status }} · {{ call.duration_ms || 0 }} ms · {{ call.error_code || '无错误' }}</small></el-timeline-item></el-timeline><el-empty v-if="!selectedRun.tool_calls.length" description="暂无工具调用" :image-size="48" /></div><div class="run-detail-section"><div class="subsection-title"><strong>模型/人工事件</strong><small>{{ selectedRun.events.length }} 条</small></div><el-timeline><el-timeline-item v-for="event in selectedRun.events" :key="event.id" :type="event.status === 'SUCCEEDED' ? 'success' : event.status === 'FAILED' ? 'danger' : 'primary'" :timestamp="formatTime(event.started_at)"><strong>{{ event.event_type }} · {{ event.provider || 'system' }}</strong><small>{{ event.status }} · {{ event.duration_ms || 0 }} ms · {{ event.error_code || '无错误' }}</small></el-timeline-item></el-timeline><el-empty v-if="!selectedRun.events.length" description="暂无运行事件" :image-size="48" /></div><div class="run-detail-section"><div class="subsection-title"><strong>状态快照</strong></div><pre class="observability-json">{{ JSON.stringify(selectedRun.state_snapshot, null, 2) }}</pre></div></div><el-empty v-else description="请选择运行记录" /></el-drawer>
  </section>
</template>
