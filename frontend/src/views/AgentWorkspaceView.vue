<script setup lang="ts">
import { computed, onMounted, reactive, shallowRef, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { DocumentChecked, Download, Refresh, VideoPause } from '@element-plus/icons-vue'
import { getApiError } from '../api/http'
import { createAgentRun, cancelAgentRun, confirmAgentRun, executeAgentRun, retryAgentRun, type AgentRun, type AgentType } from '../api/agents'
import { createReport, confirmReport, downloadReport, type Report } from '../api/reports'
import { listRegions, listStations, type RegionSummary, type Station } from '../api/catalog'
import { listCandidates, type Candidate } from '../api/operations'

interface AgentConfig {
  type: AgentType
  title: string
  eyebrow: string
  description: string
  promptVersion: string
  stages: string[]
}

const CONFIG: Record<AgentType, AgentConfig> = {
  coverage_gap: { type: 'coverage_gap', title: '覆盖缺口分析', eyebrow: 'COVERAGE GAP AGENT', description: '识别区域站点覆盖、快充比例和时段利用率缺口。', promptVersion: 'coverage-gap-v1', stages: ['业务数据', 'RAG 规范', '确定性计算', '解释与保存'] },
  competition: { type: 'competition', title: '竞争格局分析', eyebrow: 'COMPETITION AGENT', description: '分析候选点周边站点、运营商集中度和服务空白。', promptVersion: 'competition-v1', stages: ['周边站点', '运营商分析', '竞争计算', '解释与保存'] },
  site_selection: { type: 'site_selection', title: '候选选址评分', eyebrow: 'SITE SELECTION AGENT', description: '按覆盖、交通、竞争、建设条件和政策适配对候选点排序。', promptVersion: 'site-selection-v1', stages: ['候选点数据', '规则检索', '评分计算', '解释与保存'] },
  expansion: { type: 'expansion', title: '站点扩容规划', eyebrow: 'EXPANSION AGENT', description: '根据利用率、故障、容量和预算生成扩容方案。', promptVersion: 'expansion-v1', stages: ['运营与故障', '设备规范', '扩容计算', '人工确认'] },
  policy_matching: { type: 'policy_matching', title: '政策与补贴匹配', eyebrow: 'POLICY MATCHING AGENT', description: '匹配区域政策资格、补贴条件、材料清单和申请期限。', promptVersion: 'policy-matching-v1', stages: ['候选点与政策', '政策原文', '条件匹配', '解释与保存'] },
}

const route = useRoute()
const agentType = computed(() => (route.meta.agentType || 'coverage_gap') as AgentType)
const config = computed(() => CONFIG[agentType.value])
const form = reactive<Record<string, any>>({ region_code: '', charger_type: 'ALL', coverage_radius_km: 5, threshold: 0.8, analysis_date: new Date().toISOString().slice(0, 10), latitude: 34.05, longitude: -118.25, radius_km: 5, operator_code: '', candidate_site_ids: [], weights: { coverage: 0.25, traffic: 0.2, competition: 0.2, construction: 0.2, policy: 0.15 }, target_score: 70, nearby_radius_km: 5, station_ids: [], start_date: '', end_date: '', budget_usd: null, occupancy_target: 0.75, region_code_policy: '', subject_type: 'CPO', planned_scale_kw: 150, planned_fast_connectors: 4, planned_slow_connectors: 4, project_budget_usd: null, planned_date: new Date().toISOString().slice(0, 10), available_materials: [] })
const regions = shallowRef<RegionSummary[]>([])
const stations = shallowRef<Station[]>([])
const candidates = shallowRef<Candidate[]>([])
const optionsLoading = shallowRef(false)
const run = shallowRef<AgentRun | null>(null)
const report = shallowRef<Report | null>(null)
const running = shallowRef(false)
const loadingReport = shallowRef(false)
const errorMessage = shallowRef('')
const traceId = shallowRef('')
const confirmationComment = shallowRef('')
const reportComment = shallowRef('')

const statusLabel = computed(() => ({ PENDING: '待运行', RUNNING: '运行中', WAITING_CONFIRMATION: '等待确认', COMPLETED: '已完成', FAILED: '失败', BLOCKED: '数据不足', CANCELLED: '已取消' } as Record<string, string>)[run.value?.status || 'PENDING'] || run.value?.status || '待运行')
const statusType = computed(() => ({ PENDING: 'info', RUNNING: 'primary', WAITING_CONFIRMATION: 'warning', COMPLETED: 'success', FAILED: 'danger', BLOCKED: 'warning', CANCELLED: 'info' } as Record<string, string>)[run.value?.status || 'PENDING'] || 'info')
const snapshot = computed(() => run.value?.state_snapshot || {})
const currentStage = computed(() => snapshot.value.current_stage || run.value?.status || 'CREATED')
const conclusion = computed(() => snapshot.value.conclusion?.conclusion || snapshot.value.conclusion?.message || '')
const evidence = computed(() => snapshot.value.evidence || [])
const mysqlEvidence = computed(() => Object.entries(snapshot.value.tool_results || {}))
const calculationEvidence = computed(() => Object.entries(snapshot.value.calculation_results || {}))
const timeline = computed(() => {
  const events = (run.value?.events || []).map((event) => ({ key: `event-${event.id}`, sequence: event.sequence_no, label: event.event_type, status: event.status, detail: event.model_name || event.provider || event.error_code || '', time: event.finished_at || event.started_at || '' }))
  const tools = (run.value?.tool_calls || []).map((tool) => ({ key: `tool-${tool.id}`, sequence: tool.sequence_no, label: `TOOL · ${tool.tool_name}`, status: tool.status, detail: tool.error_code || `${tool.duration_ms ?? '-'} ms`, time: tool.finished_at || tool.started_at || '' }))
  return [...events, ...tools].sort((left, right) => left.sequence - right.sequence)
})
const canRun = computed(() => !running.value && !['WAITING_CONFIRMATION', 'COMPLETED'].includes(run.value?.status || ''))
const runProgress = computed(() => {
  if (run.value?.status === 'COMPLETED') return 100
  if (run.value?.status === 'WAITING_CONFIRMATION') return 86
  if (run.value?.status === 'FAILED' || run.value?.status === 'BLOCKED' || run.value?.status === 'CANCELLED') return 100
  const stage = String(currentStage.value)
  if (stage.includes('BUSINESS') || stage.includes('QUERY')) return 24
  if (stage.includes('RAG') || stage.includes('RETRIEV')) return 46
  if (stage.includes('CALC')) return 66
  if (stage.includes('EXPLAIN') || stage.includes('SAVE')) return 84
  return run.value?.status === 'RUNNING' ? 15 : 0
})

function pretty(value: unknown) {
  return JSON.stringify(value, null, 2)
}

function resetAgentForm() {
  form.region_code = regions.value[0]?.region_code || ''
  form.region_code_policy = regions.value[0]?.region_code || ''
  form.candidate_site_ids = []
  form.station_ids = []
  form.available_materials = []
  run.value = null
  report.value = null
  errorMessage.value = ''
  traceId.value = ''
  confirmationComment.value = ''
  reportComment.value = ''
}

async function loadOptions() {
  optionsLoading.value = true
  try {
    const tasks: Array<Promise<unknown>> = []
    if (agentType.value === 'coverage_gap' || agentType.value === 'policy_matching' || agentType.value === 'site_selection') tasks.push(listRegions({ page: 1, page_size: 200 }).then((response) => { regions.value = response.items }))
    if (agentType.value === 'site_selection' || agentType.value === 'policy_matching') tasks.push(listCandidates({ page: 1, page_size: 200 }).then((response) => { candidates.value = response.items }))
    if (agentType.value === 'expansion' || agentType.value === 'competition') tasks.push(listStations({ page: 1, page_size: 200 }).then((response) => { stations.value = response.items }))
    await Promise.all(tasks)
    resetAgentForm()
  } catch (error) {
    const detail = getApiError(error)
    errorMessage.value = detail.message
    traceId.value = detail.traceId
  } finally {
    optionsLoading.value = false
  }
}

function inputPayload() {
  if (agentType.value === 'coverage_gap') return { data_version: form.data_version || undefined, prompt_version: config.value.promptVersion, region_code: form.region_code, charger_type: form.charger_type, coverage_radius_km: Number(form.coverage_radius_km), threshold: Number(form.threshold), analysis_date: form.analysis_date || undefined }
  if (agentType.value === 'competition') return { prompt_version: config.value.promptVersion, latitude: Number(form.latitude), longitude: Number(form.longitude), radius_km: Number(form.radius_km), operator_code: form.operator_code || undefined, analysis_date: form.analysis_date || undefined }
  if (agentType.value === 'site_selection') return { prompt_version: config.value.promptVersion, candidate_site_ids: form.candidate_site_ids, weights: form.weights, target_score: Number(form.target_score), nearby_radius_km: Number(form.nearby_radius_km), scoring_rule_version: 'site-selection-score-v1' }
  if (agentType.value === 'expansion') return { prompt_version: config.value.promptVersion, station_ids: form.station_ids, start_date: form.start_date || undefined, end_date: form.end_date || undefined, budget_usd: form.budget_usd == null ? undefined : Number(form.budget_usd), occupancy_target: Number(form.occupancy_target), high_occupancy_threshold: 0.9, fault_window_days: 30 }
  return { prompt_version: config.value.promptVersion, region_code: form.region_code_policy, subject_type: form.subject_type, candidate_site_ids: form.candidate_site_ids, planned_scale_kw: Number(form.planned_scale_kw), planned_fast_connectors: Number(form.planned_fast_connectors), planned_slow_connectors: Number(form.planned_slow_connectors), project_budget_usd: form.project_budget_usd == null ? undefined : Number(form.project_budget_usd), available_materials: form.available_materials, planned_date: form.planned_date || undefined }
}

function validateInput() {
  if (agentType.value === 'coverage_gap' && !form.region_code) return '请选择区域。'
  if (agentType.value === 'site_selection' && !form.candidate_site_ids.length) return '请选择至少一个候选站点。'
  if (agentType.value === 'expansion' && !form.station_ids.length) return '请选择至少一个站点。'
  if (agentType.value === 'policy_matching' && !form.region_code_policy) return '请选择政策区域。'
  return ''
}

async function startRun() {
  const invalid = validateInput()
  if (invalid) { ElMessage.warning(invalid); return }
  running.value = true
  errorMessage.value = ''
  traceId.value = ''
  try {
    const payload = inputPayload()
    const created = await createAgentRun({ agent_type: agentType.value, input_payload: payload, business_scope: { region_code: form.region_code || form.region_code_policy || undefined }, prompt_version: config.value.promptVersion })
    run.value = created
    const completed = await executeAgentRun(created.run_id, { max_model_calls: 3, max_tool_calls: 20, max_loop_iterations: 8, max_duration_seconds: 120 })
    run.value = completed
    await loadReport(completed)
    window.dispatchEvent(new CustomEvent('chargeops:agent-completed', { detail: completed }))
  } catch (error) {
    const detail = getApiError(error)
    errorMessage.value = detail.message
    traceId.value = detail.traceId
  } finally {
    running.value = false
  }
}

async function cancelRun() {
  if (!run.value) return
  try { run.value = await cancelAgentRun(run.value.run_id); ElMessage.info('Agent 运行已取消。') } catch (error) { ElMessage.error(getApiError(error).message) }
}

async function retryRun() {
  if (!run.value) return
  running.value = true
  try { const retried = await retryAgentRun(run.value.run_id); run.value = await executeAgentRun(retried.run_id); await loadReport(run.value) } catch (error) { ElMessage.error(getApiError(error).message) } finally { running.value = false }
}

async function confirmRun(decision: 'APPROVE' | 'REJECT') {
  if (!run.value || !confirmationComment.value.trim()) { ElMessage.warning('请填写确认意见。'); return }
  try { run.value = await confirmAgentRun(run.value.run_id, decision, confirmationComment.value.trim()); confirmationComment.value = ''; await loadReport(run.value) } catch (error) { ElMessage.error(getApiError(error).message) }
}

async function loadReport(currentRun: AgentRun) {
  if (!['COMPLETED', 'WAITING_CONFIRMATION'].includes(currentRun.status)) return
  loadingReport.value = true
  try { report.value = await createReport(currentRun.run_id, `${config.value.title} · ${currentRun.run_id.slice(0, 8)}`) } catch { /* 报告可稍后从运行记录重试创建。 */ } finally { loadingReport.value = false }
}

async function confirmDecision(decision: 'APPROVE' | 'REJECT') {
  if (!report.value || !reportComment.value.trim()) { ElMessage.warning('请填写报告确认意见。'); return }
  try { report.value = await confirmReport(report.value.report_id, decision, reportComment.value.trim()); reportComment.value = '' } catch (error) { ElMessage.error(getApiError(error).message) }
}

async function exportReport(format: 'markdown' | 'json') {
  if (!report.value) return
  try { await downloadReport(report.value.report_id, format) } catch (error) { ElMessage.error(getApiError(error).message) }
}

async function retryReportCreation() {
  if (run.value) await loadReport(run.value)
}

watch(agentType, loadOptions)
onMounted(loadOptions)
</script>

<template>
  <section class="agent-page">
    <div class="agent-header"><div><span class="eyebrow">{{ config.eyebrow }}</span><h2>{{ config.title }}</h2><p>{{ config.description }}</p></div><div class="agent-header-actions"><el-tag v-if="run" :type="statusType">{{ statusLabel }}</el-tag><el-button v-if="run && ['FAILED', 'BLOCKED'].includes(run.status)" @click="retryRun">重试运行</el-button><el-button v-if="run && running" type="danger" plain @click="cancelRun"><el-icon><VideoPause /></el-icon>取消运行</el-button></div></div>
    <el-alert v-if="errorMessage" class="page-alert" type="error" :closable="false" show-icon :title="errorMessage"><template #default><span v-if="traceId">trace_id: {{ traceId }}</span><el-button text type="primary" @click="startRun">重试</el-button></template></el-alert>
    <div class="agent-layout">
      <el-card class="agent-input-card"><template #header><div class="card-header"><div><strong>分析参数</strong><small>输入会按 Agent Schema 校验并保留在运行快照中</small></div><el-tag type="info" effect="plain">{{ config.promptVersion }}</el-tag></div></template>
        <el-form label-position="top" :disabled="running" class="agent-form">
          <template v-if="agentType === 'coverage_gap'"><el-form-item label="分析区域" required><el-select v-model="form.region_code" filterable placeholder="选择区域"><el-option v-for="region in regions" :key="region.region_code" :label="`${region.name} · ${region.region_code}`" :value="region.region_code" /></el-select></el-form-item><el-form-item label="充电类型"><el-radio-group v-model="form.charger_type"><el-radio-button value="ALL">全部</el-radio-button><el-radio-button value="FAST">快充</el-radio-button><el-radio-button value="SLOW">慢充</el-radio-button></el-radio-group></el-form-item><div class="form-grid form-grid--two"><el-form-item label="覆盖半径（km）"><el-input-number v-model="form.coverage_radius_km" :min="0.1" :max="100" :step="0.5" /></el-form-item><el-form-item label="覆盖阈值"><el-input-number v-model="form.threshold" :min="0" :max="1" :step="0.05" /></el-form-item></div><el-form-item label="分析日期"><el-date-picker v-model="form.analysis_date" type="date" value-format="YYYY-MM-DD" /></el-form-item></template>
          <template v-else-if="agentType === 'competition'"><div class="form-grid form-grid--two"><el-form-item label="纬度" required><el-input-number v-model="form.latitude" :precision="6" :step="0.0001" /></el-form-item><el-form-item label="经度" required><el-input-number v-model="form.longitude" :precision="6" :step="0.0001" /></el-form-item></div><el-form-item label="分析半径（km）"><el-input-number v-model="form.radius_km" :min="0.1" :max="100" :step="0.5" /></el-form-item><el-form-item label="目标运营商编码"><el-input v-model="form.operator_code" clearable placeholder="可选，例如 OP-001" /></el-form-item><el-form-item label="分析日期"><el-date-picker v-model="form.analysis_date" type="date" value-format="YYYY-MM-DD" /></el-form-item></template>
          <template v-else-if="agentType === 'site_selection'"><el-form-item label="候选站点" required><el-select v-model="form.candidate_site_ids" multiple filterable collapse-tags placeholder="选择候选站点"><el-option v-for="candidate in candidates" :key="candidate.id" :label="`${candidate.site_name} · ${candidate.external_candidate_id}`" :value="candidate.id" /></el-select></el-form-item><div class="form-grid form-grid--two"><el-form-item label="目标总分"><el-input-number v-model="form.target_score" :min="0" :max="100" /></el-form-item><el-form-item label="周边半径（km）"><el-input-number v-model="form.nearby_radius_km" :min="0.1" :max="100" :step="0.5" /></el-form-item></div><div class="weight-grid"><div v-for="(weight, key) in form.weights" :key="key"><label>{{ key }}</label><el-input-number v-model="form.weights[key]" :min="0" :max="1" :step="0.05" size="small" /></div></div></template>
          <template v-else-if="agentType === 'expansion'"><el-form-item label="分析站点" required><el-select v-model="form.station_ids" multiple filterable collapse-tags placeholder="选择站点"><el-option v-for="station in stations" :key="station.id" :label="`${station.station_name} · ${station.external_station_id}`" :value="station.id" /></el-select></el-form-item><div class="form-grid form-grid--two"><el-form-item label="开始日期"><el-date-picker v-model="form.start_date" type="date" value-format="YYYY-MM-DD" /></el-form-item><el-form-item label="结束日期"><el-date-picker v-model="form.end_date" type="date" value-format="YYYY-MM-DD" /></el-form-item></div><el-form-item label="预算上限（USD）"><el-input-number v-model="form.budget_usd" :min="0" :step="5000" /></el-form-item><el-form-item label="目标利用率"><el-input-number v-model="form.occupancy_target" :min="0" :max="1" :step="0.05" /></el-form-item></template>
          <template v-else><el-form-item label="政策区域" required><el-select v-model="form.region_code_policy" filterable placeholder="选择区域"><el-option v-for="region in regions" :key="region.region_code" :label="`${region.name} · ${region.region_code}`" :value="region.region_code" /></el-select></el-form-item><el-form-item label="申请主体"><el-input v-model="form.subject_type" placeholder="例如 CPO、园区、商业地产" /></el-form-item><el-form-item label="候选站点"><el-select v-model="form.candidate_site_ids" multiple filterable collapse-tags placeholder="可选"><el-option v-for="candidate in candidates" :key="candidate.id" :label="candidate.site_name" :value="candidate.id" /></el-select></el-form-item><div class="form-grid form-grid--two"><el-form-item label="规划规模（kW）"><el-input-number v-model="form.planned_scale_kw" :min="0" :step="10" /></el-form-item><el-form-item label="项目预算（USD）"><el-input-number v-model="form.project_budget_usd" :min="0" :step="5000" /></el-form-item><el-form-item label="规划快充数"><el-input-number v-model="form.planned_fast_connectors" :min="0" /></el-form-item><el-form-item label="规划慢充数"><el-input-number v-model="form.planned_slow_connectors" :min="0" /></el-form-item></div><el-form-item label="计划日期"><el-date-picker v-model="form.planned_date" type="date" value-format="YYYY-MM-DD" /></el-form-item></template>
          <el-button class="agent-run-button" type="primary" size="large" :loading="running || optionsLoading" @click="startRun">{{ running ? 'Agent 运行中…' : '开始分析' }}</el-button>
        </el-form>
      </el-card>

      <div class="agent-result-column">
        <el-card class="agent-progress-card"><template #header><div class="card-header"><div><strong>运行进度</strong><small>{{ run ? `${run.run_id} · ${currentStage}` : '尚未创建运行' }}</small></div><el-tag :type="statusType" effect="plain">{{ statusLabel }}</el-tag></div></template><el-progress :percentage="runProgress" :status="statusType === 'danger' ? 'exception' : statusType === 'success' ? 'success' : undefined" /><div class="agent-stage-list"><div v-for="(stage, index) in config.stages" :key="stage" class="agent-stage" :class="{ 'agent-stage--active': currentStage.toLowerCase().includes(stage.split(' ')[0].toLowerCase()) || (index === 0 && runProgress > 0 && runProgress < 30), 'agent-stage--done': runProgress >= (index + 1) * 25 }"><span>{{ String(index + 1).padStart(2, '0') }}</span><strong>{{ stage }}</strong></div></div><div v-if="run?.stop_reason" class="stop-reason"><strong>停止原因：</strong>{{ run.stop_reason }}</div><div v-if="run?.state_snapshot.errors?.length" class="run-errors"><div v-for="(item, index) in run.state_snapshot.errors" :key="index"><el-tag size="small" type="danger">{{ String(item.code || 'ERROR') }}</el-tag><span>{{ String(item.message || '') }}</span></div></div></el-card>
        <el-card class="agent-conclusion-card"><template #header><div class="card-header"><div><strong>分析结论</strong><small>确定性计算、模型解释和停止状态</small></div><el-button v-if="run && ['FAILED', 'BLOCKED'].includes(run.status)" text type="primary" @click="retryRun"><el-icon><Refresh /></el-icon>重试</el-button></div></template><el-empty v-if="!run" description="提交参数后查看 Agent 结果" :image-size="60" /><template v-else><div v-if="conclusion" class="conclusion-text">{{ conclusion }}</div><div v-else class="muted-copy">当前运行尚未生成最终结论。</div><div v-if="run.status === 'WAITING_CONFIRMATION'" class="confirmation-panel"><div><strong>需要人工确认</strong><small>{{ agentType === 'expansion' ? '扩容方案会影响业务资源，确认后才会继续保存。' : '请确认当前分析结果后继续。' }}</small></div><el-input v-model="confirmationComment" type="textarea" :rows="2" placeholder="填写确认或拒绝意见" /><div class="confirmation-actions"><el-button type="danger" plain @click="confirmRun('REJECT')">拒绝</el-button><el-button type="primary" @click="confirmRun('APPROVE')">批准继续</el-button></div></div></template></el-card>
      </div>
    </div>

    <div class="agent-evidence-grid"><el-card><template #header><div class="card-header"><div><strong>MySQL 业务数据</strong><small>工具查询结果</small></div><el-tag type="info" effect="plain">{{ mysqlEvidence.length }}</el-tag></div></template><el-empty v-if="!mysqlEvidence.length" description="暂无业务数据证据" :image-size="54" /><div v-else class="json-evidence-list"><div v-for="[key, value] in mysqlEvidence" :key="key"><strong>{{ key }}</strong><pre>{{ pretty(value) }}</pre></div></div></el-card><el-card><template #header><div class="card-header"><div><strong>RAG 原文证据</strong><small>文档、Chunk 和原文位置</small></div><el-tag type="info" effect="plain">{{ evidence.length }}</el-tag></div></template><el-empty v-if="!evidence.length" description="暂无 RAG 证据" :image-size="54" /><div v-else class="rag-evidence-list"><div v-for="(item, index) in evidence" :key="index" class="rag-evidence-item"><div><el-tag size="small" type="success">{{ String(item.document_type || item.doc_type || 'DOCUMENT') }}</el-tag><strong>{{ String(item.title || item.document_title || `证据 ${index + 1}`) }}</strong></div><p>{{ String(item.fragment || item.content || item.text || '未返回原文片段') }}</p><small>{{ String(item.original_href || item.source_url || '') }}</small></div></div></el-card><el-card><template #header><div class="card-header"><div><strong>确定性计算</strong><small>规则版本和计算输出</small></div><el-tag type="info" effect="plain">{{ calculationEvidence.length }}</el-tag></div></template><el-empty v-if="!calculationEvidence.length" description="暂无计算结果" :image-size="54" /><div v-else class="json-evidence-list"><div v-for="[key, value] in calculationEvidence" :key="key"><strong>{{ key }}</strong><pre>{{ pretty(value) }}</pre></div></div></el-card></div>

    <div class="agent-bottom-grid"><el-card class="timeline-card"><template #header><div class="card-header"><div><strong>运行轨迹</strong><small>模型调用、工具调用、RAG 查询与阶段事件</small></div><el-tag type="info" effect="plain">{{ timeline.length }}</el-tag></div></template><el-empty v-if="!timeline.length" description="运行后展示轨迹" :image-size="54" /><el-timeline v-else><el-timeline-item v-for="item in timeline" :key="item.key" :timestamp="item.time" :type="item.status === 'SUCCEEDED' ? 'success' : item.status === 'FAILED' ? 'danger' : 'primary'"><strong>{{ item.label }}</strong><small>{{ item.status }} · {{ item.detail }}</small></el-timeline-item></el-timeline></el-card><el-card class="report-card"><template #header><div class="card-header"><div><strong>决策报告与确认</strong><small>支持人工确认和 Markdown / JSON 导出</small></div><el-icon v-if="loadingReport" class="is-loading"><Refresh /></el-icon></div></template><el-empty v-if="!report" description="运行结束后生成报告" :image-size="54"><template #default><el-button v-if="run && ['COMPLETED', 'WAITING_CONFIRMATION'].includes(run.status)" type="primary" @click="retryReportCreation">生成报告</el-button></template></el-empty><template v-else><div class="report-meta"><el-tag :type="report.status === 'APPROVED' ? 'success' : report.status === 'WAITING_CONFIRMATION' ? 'warning' : 'info'">{{ report.status }}</el-tag><span>{{ report.report_id }}</span></div><p>{{ report.conclusion || '暂无报告结论' }}</p><div v-if="report.status === 'WAITING_CONFIRMATION'" class="report-confirm"><el-input v-model="reportComment" type="textarea" :rows="2" placeholder="填写报告确认意见" /><div class="confirmation-actions"><el-button type="danger" plain @click="confirmDecision('REJECT')">拒绝报告</el-button><el-button type="primary" @click="confirmDecision('APPROVE')">批准报告</el-button></div></div><div class="report-actions"><el-button size="small" @click="exportReport('markdown')"><el-icon><Download /></el-icon>Markdown</el-button><el-button size="small" @click="exportReport('json')"><el-icon><DocumentChecked /></el-icon>JSON</el-button></div></template></el-card></div>
  </section>
</template>

