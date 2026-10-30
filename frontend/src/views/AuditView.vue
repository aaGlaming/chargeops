<script setup lang="ts">
import { onMounted, reactive, shallowRef } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { getApiError } from '../api/http'
import { listAuditLogs, type AuditLogItem } from '../api/observability'

const filters = reactive({ action: '', resourceType: '', severity: '' })
const items = shallowRef<AuditLogItem[]>([])
const loading = shallowRef(false)
const errorMessage = shallowRef('')
const traceId = shallowRef('')
const page = shallowRef(1)
const total = shallowRef(0)
const selected = shallowRef<AuditLogItem | null>(null)
const drawerVisible = shallowRef(false)
function severityType(value: string) { return value === 'ERROR' ? 'danger' : value === 'WARNING' ? 'warning' : 'info' }
function formatTime(value: string) { return new Date(value).toLocaleString('zh-CN', { hour12: false }) }
function pretty(value: unknown) { return JSON.stringify(value || {}, null, 2) }
async function loadAudit() { loading.value = true; errorMessage.value = ''; try { const response = await listAuditLogs({ page: page.value, page_size: 50, action: filters.action || undefined, resource_type: filters.resourceType || undefined, severity: filters.severity || undefined }); items.value = response.items; total.value = Number(response.page.total || 0) } catch (error) { const detail = getApiError(error); errorMessage.value = detail.message; traceId.value = detail.traceId } finally { loading.value = false } }
function openAudit(item: AuditLogItem) { selected.value = item; drawerVisible.value = true }
onMounted(loadAudit)
</script>

<template>
  <section class="observability-page"><div class="observability-toolbar"><div><span class="eyebrow">AUDIT / IMMUTABLE EVENTS</span><h2>审计日志</h2><p>查询登录、权限拒绝、导入、删除、确认、发布和告警操作。</p></div><el-button :loading="loading" @click="loadAudit"><el-icon><Refresh /></el-icon>刷新</el-button></div><el-alert v-if="errorMessage" class="page-alert" type="error" :closable="false" show-icon :title="errorMessage"><template #default><span v-if="traceId">trace_id: {{ traceId }}</span><el-button text type="primary" @click="loadAudit">重试</el-button></template></el-alert><el-card class="observability-card"><div class="observability-filter-row"><el-input v-model="filters.action" clearable placeholder="动作，例如 IMPORT_BATCH" @keyup.enter="page = 1; loadAudit()" /><el-input v-model="filters.resourceType" clearable placeholder="资源类型" @keyup.enter="page = 1; loadAudit()" /><el-select v-model="filters.severity" clearable placeholder="严重级别"><el-option label="INFO" value="INFO" /><el-option label="WARNING" value="WARNING" /><el-option label="ERROR" value="ERROR" /></el-select><el-button type="primary" @click="page = 1; loadAudit()">查询</el-button><el-tag type="info" effect="plain">{{ total }} 条</el-tag></div><el-table v-loading="loading" :data="items" size="small" height="560" empty-text="暂无审计日志" @row-click="openAudit"><el-table-column prop="occurred_at" label="时间" width="175"><template #default="scope">{{ formatTime(scope.row.occurred_at) }}</template></el-table-column><el-table-column prop="action" label="动作" min-width="180" /><el-table-column prop="resource_type" label="资源" width="130" /><el-table-column prop="resource_id" label="资源 ID" min-width="150" /><el-table-column label="级别" width="90"><template #default="scope"><el-tag size="small" :type="severityType(scope.row.severity)">{{ scope.row.severity }}</el-tag></template></el-table-column><el-table-column prop="trace_id" label="Trace ID" min-width="170" show-overflow-tooltip /><el-table-column prop="actor_user_id" label="用户" width="70" /></el-table></el-card><div class="table-pagination"><el-pagination v-model:current-page="page" background layout="prev, pager, next" :page-size="50" :total="total" @current-change="loadAudit" /></div><el-drawer v-model="drawerVisible" title="审计事件详情" size="570px"><template v-if="selected"><div class="audit-detail"><el-descriptions :column="1" border size="small"><el-descriptions-item label="动作">{{ selected.action }}</el-descriptions-item><el-descriptions-item label="资源">{{ selected.resource_type }} / {{ selected.resource_id || '-' }}</el-descriptions-item><el-descriptions-item label="请求 ID">{{ selected.request_id || '-' }}</el-descriptions-item><el-descriptions-item label="Trace ID">{{ selected.trace_id || '-' }}</el-descriptions-item><el-descriptions-item label="Agent Run ID">{{ selected.agent_run_id || '-' }}</el-descriptions-item><el-descriptions-item label="Tool Call ID">{{ selected.tool_call_id || '-' }}</el-descriptions-item><el-descriptions-item label="Import Batch ID">{{ selected.import_batch_id || '-' }}</el-descriptions-item></el-descriptions><div class="audit-json-block"><strong>变更前</strong><pre class="observability-json">{{ pretty(selected.before_state) }}</pre></div><div class="audit-json-block"><strong>变更后</strong><pre class="observability-json">{{ pretty(selected.after_state) }}</pre></div><div class="audit-json-block"><strong>元数据</strong><pre class="observability-json">{{ pretty(selected.metadata) }}</pre></div></div></template></el-drawer></section>
</template>
