<script setup lang="ts">
import { computed, onMounted, reactive, shallowRef, watch } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Aim } from '@element-plus/icons-vue'
import { getApiError } from '../api/http'
import { createCandidate, deleteCandidate, getCandidate, listCandidates, updateCandidate, type Candidate, type CandidateDetail, type CandidatePayload } from '../api/operations'
import { useAuth } from '../stores/auth'

const auth = useAuth()
const filters = reactive({ regionCode: '', lifecycleStatus: '' })
const candidates = shallowRef<Candidate[]>([])
const loading = shallowRef(false)
const errorMessage = shallowRef('')
const traceId = shallowRef('')
const page = shallowRef(1)
const total = shallowRef(0)
const selectedCandidate = shallowRef<CandidateDetail | null>(null)
const detailDrawerVisible = shallowRef(false)
const detailLoading = shallowRef(false)
const dialogVisible = shallowRef(false)
const editingId = shallowRef<number | null>(null)
const formRef = shallowRef<FormInstance>()
const form = reactive<CandidatePayload>({ external_candidate_id: '', site_name: '', region_code: '', city: '', state: '', latitude: null, longitude: null, area_sqm: null, parking_spaces: null, electric_capacity_kw: null, budget_usd: null, traffic_index: null, population_density: null, planned_open_date: null, data_as_of: new Date().toISOString().slice(0, 10), lifecycle_status: 'DRAFT', source_type: 'user_upload', data_version: new Date().toISOString().slice(0, 10) })
const rules: FormRules = { external_candidate_id: [{ required: true, message: '请输入候选点 ID', trigger: 'blur' }], site_name: [{ required: true, message: '请输入候选点名称', trigger: 'blur' }], region_code: [{ required: true, message: '请输入区域编码', trigger: 'blur' }], latitude: [{ type: 'number', min: -90, max: 90, message: '纬度范围应为 -90 到 90', trigger: 'blur' }], longitude: [{ type: 'number', min: -180, max: 180, message: '经度范围应为 -180 到 180', trigger: 'blur' }] }

const canWrite = computed(() => auth.hasPermission('candidate.write'))

function statusType(status: string) {
  return ({ DRAFT: 'info', REVIEW: 'warning', RECOMMENDED: 'success', ARCHIVED: 'info' } as Record<string, string>)[status] || 'info'
}

function sourceLabel(value: string) {
  return ({ public: '公开', user_upload: '上传', synthetic: '合成', agent: 'Agent' } as Record<string, string>)[value] || value
}

async function loadCandidates() {
  loading.value = true
  errorMessage.value = ''
  traceId.value = ''
  try {
    const response = await listCandidates({ region_code: filters.regionCode || undefined, lifecycle_status: filters.lifecycleStatus || undefined, page: page.value, page_size: 25 })
    candidates.value = response.items
    total.value = response.page.total
  } catch (error) {
    const detail = getApiError(error)
    errorMessage.value = detail.message
    traceId.value = detail.traceId
  } finally {
    loading.value = false
  }
}

function resetForm() {
  Object.assign(form, { external_candidate_id: '', site_name: '', region_code: '', city: '', state: '', latitude: null, longitude: null, area_sqm: null, parking_spaces: null, electric_capacity_kw: null, budget_usd: null, traffic_index: null, population_density: null, planned_open_date: null, data_as_of: new Date().toISOString().slice(0, 10), lifecycle_status: 'DRAFT', source_type: 'user_upload', data_version: new Date().toISOString().slice(0, 10) })
  formRef.value?.clearValidate()
}

function openCreate() {
  editingId.value = null
  resetForm()
  dialogVisible.value = true
}

function openEdit(candidate: Candidate) {
  editingId.value = candidate.id
  Object.assign(form, { external_candidate_id: candidate.external_candidate_id, site_name: candidate.site_name, region_code: candidate.region?.region_code || '', city: candidate.city || '', state: candidate.state || '', latitude: candidate.latitude ?? null, longitude: candidate.longitude ?? null, area_sqm: candidate.area_sqm ?? null, parking_spaces: candidate.parking_spaces ?? null, electric_capacity_kw: candidate.electric_capacity_kw ?? null, budget_usd: candidate.budget_usd ?? null, traffic_index: candidate.traffic_index ?? null, population_density: candidate.population_density ?? null, planned_open_date: candidate.planned_open_date || null, data_as_of: candidate.data_as_of || null, lifecycle_status: candidate.lifecycle_status, source_type: candidate.source.source_type, data_version: candidate.source.data_version })
  dialogVisible.value = true
}

async function saveCandidate() {
  if (!canWrite.value) return
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  try {
    if (editingId.value) await updateCandidate(editingId.value, form)
    else await createCandidate(form)
    dialogVisible.value = false
    ElMessage.success(editingId.value ? '候选站点已更新。' : '候选站点已创建。')
    await loadCandidates()
  } catch (error) {
    const detail = getApiError(error)
    ElMessage.error(detail.traceId ? `${detail.message}（trace_id: ${detail.traceId}）` : detail.message)
  }
}

async function removeCandidate(candidate: Candidate) {
  try {
    await ElMessageBox.confirm(`确认删除候选站点“${candidate.site_name}”？删除后仍会保留审计记录。`, '删除候选站点', { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' })
    await deleteCandidate(candidate.id)
    ElMessage.success('候选站点已删除。')
    await loadCandidates()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(getApiError(error).message)
  }
}

async function openDetail(candidateId: number) {
  detailDrawerVisible.value = true
  detailLoading.value = true
  selectedCandidate.value = null
  try {
    selectedCandidate.value = await getCandidate(candidateId)
  } catch (error) {
    ElMessage.error(getApiError(error).message)
  } finally {
    detailLoading.value = false
  }
}

watch(() => [filters.regionCode, filters.lifecycleStatus], () => { page.value = 1; loadCandidates() })
onMounted(loadCandidates)
</script>

<template>
  <section class="candidates-page">
    <div class="page-toolbar station-toolbar"><div class="data-freshness"><span class="status-dot" /> 共 {{ total.toLocaleString() }} 个候选站点</div><el-button v-if="canWrite" type="primary" @click="openCreate">新建候选站点</el-button></div>
    <el-card class="filter-card"><div class="candidate-filter-row"><el-form-item label="区域编码"><el-input v-model="filters.regionCode" clearable placeholder="例如 CA-06037" @keyup.enter="loadCandidates" /></el-form-item><el-form-item label="生命周期"><el-select v-model="filters.lifecycleStatus" clearable placeholder="全部状态"><el-option label="草稿" value="DRAFT" /><el-option label="待审核" value="REVIEW" /><el-option label="已推荐" value="RECOMMENDED" /><el-option label="已归档" value="ARCHIVED" /></el-select></el-form-item><el-button @click="loadCandidates">查询</el-button></div></el-card>
    <el-alert v-if="errorMessage" class="page-alert" type="error" :closable="false" show-icon :title="errorMessage"><template #default><span v-if="traceId">trace_id: {{ traceId }}</span><el-button text type="primary" @click="loadCandidates">重试</el-button></template></el-alert>
    <el-card class="candidate-table-card"><template #header><div class="card-header"><div><strong>候选站点列表</strong><small>点击行查看坐标、建设条件、周边站点和政策关联</small></div><el-tag type="info" effect="plain">{{ total.toLocaleString() }} 条</el-tag></div></template><el-table v-loading="loading" :data="candidates" size="small" empty-text="暂无候选站点" @row-click="(row: Candidate) => openDetail(row.id)"><el-table-column label="候选点" min-width="210"><template #default="scope"><div class="station-name-cell"><strong>{{ scope.row.site_name }}</strong><small>{{ scope.row.external_candidate_id }} · {{ scope.row.region?.name || '未关联区域' }}</small></div></template></el-table-column><el-table-column label="坐标" min-width="125"><template #default="scope">{{ scope.row.latitude ?? '-' }}, {{ scope.row.longitude ?? '-' }}</template></el-table-column><el-table-column label="预算 USD" width="110"><template #default="scope">{{ scope.row.budget_usd?.toLocaleString() || '-' }}</template></el-table-column><el-table-column label="电力 kW" width="92"><template #default="scope">{{ scope.row.electric_capacity_kw || '-' }}</template></el-table-column><el-table-column label="完整度" width="92"><template #default="scope"><el-progress :percentage="Math.round(scope.row.completeness.score * 100)" :show-text="false" /><small>{{ Math.round(scope.row.completeness.score * 100) }}%</small></template></el-table-column><el-table-column label="状态" width="92"><template #default="scope"><el-tag size="small" :type="statusType(scope.row.lifecycle_status)">{{ scope.row.lifecycle_status }}</el-tag></template></el-table-column><el-table-column label="来源" width="75"><template #default="scope"><el-tag size="small" effect="plain">{{ sourceLabel(scope.row.source.source_type) }}</el-tag></template></el-table-column><el-table-column v-if="canWrite" label="操作" width="135" fixed="right"><template #default="scope"><el-button link type="primary" @click.stop="openEdit(scope.row)">编辑</el-button><el-button link type="danger" @click.stop="removeCandidate(scope.row)">删除</el-button></template></el-table-column></el-table><div class="table-pagination"><el-pagination v-model:current-page="page" background layout="prev, pager, next" :total="total" @current-change="(value: number) => { page = value; loadCandidates() }" /></div></el-card>

    <el-drawer v-model="detailDrawerVisible" title="候选站点详情" size="560px"><div v-loading="detailLoading" class="candidate-detail-drawer"><template v-if="selectedCandidate"><div class="detail-hero"><div class="workspace-icon"><el-icon><Aim /></el-icon></div><div><span class="eyebrow">{{ selectedCandidate.external_candidate_id }}</span><h2>{{ selectedCandidate.site_name }}</h2><p>{{ selectedCandidate.city || '未知城市' }} · {{ selectedCandidate.region?.name || '未关联区域' }}</p></div><el-tag :type="statusType(selectedCandidate.lifecycle_status)">{{ selectedCandidate.lifecycle_status }}</el-tag></div><el-descriptions :column="2" border size="small"><el-descriptions-item label="经纬度">{{ selectedCandidate.latitude ?? '-' }}, {{ selectedCandidate.longitude ?? '-' }}</el-descriptions-item><el-descriptions-item label="数据状态">{{ selectedCandidate.data_status }}</el-descriptions-item><el-descriptions-item label="预算 USD">{{ selectedCandidate.budget_usd?.toLocaleString() || '-' }}</el-descriptions-item><el-descriptions-item label="电力容量">{{ selectedCandidate.electric_capacity_kw || '-' }} kW</el-descriptions-item><el-descriptions-item label="交通指数">{{ selectedCandidate.traffic_index ?? '-' }}</el-descriptions-item><el-descriptions-item label="人口密度">{{ selectedCandidate.population_density ?? '-' }}</el-descriptions-item><el-descriptions-item label="可推荐">{{ selectedCandidate.completeness.recommendable ? '是' : '否' }}</el-descriptions-item><el-descriptions-item label="数据新鲜度">{{ selectedCandidate.freshness.status }}</el-descriptions-item></el-descriptions><div class="detail-section"><div class="detail-section-title"><strong>周边站点</strong><small>{{ selectedCandidate.nearby_stations.length }} 个</small></div><el-empty v-if="!selectedCandidate.nearby_stations.length" description="暂无周边站点" :image-size="52" /><div v-else class="nearby-station-list"><button v-for="station in selectedCandidate.nearby_stations" :key="station.id" type="button" @click="detailDrawerVisible = false"><strong>{{ station.station_name }}</strong><small>{{ station.total_connector_count }} 个连接器 · {{ station.operator?.operator_name || '未关联运营商' }}</small></button></div></div><div class="detail-section"><div class="detail-section-title"><strong>缺失字段</strong></div><el-tag v-for="field in selectedCandidate.completeness.missing_fields" :key="field" type="warning" effect="plain">{{ field }}</el-tag><span v-if="!selectedCandidate.completeness.missing_fields.length" class="muted-copy">关键字段完整</span></div><div class="detail-section"><div class="detail-section-title"><strong>区域政策</strong><small>{{ selectedCandidate.policies.length }} 条</small></div><el-empty v-if="!selectedCandidate.policies.length" description="暂无关联政策" :image-size="48" /><div v-else class="policy-chip-list"><el-tag v-for="(policy, index) in selectedCandidate.policies" :key="index" effect="plain">{{ String(policy.title || policy.policy_code || `政策 ${index + 1}`) }}</el-tag></div></div></template></div></el-drawer>

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑候选站点' : '新建候选站点'" width="720px" destroy-on-close><el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="candidate-form"><div class="form-grid form-grid--two"><el-form-item label="候选点 ID" prop="external_candidate_id"><el-input v-model="form.external_candidate_id" placeholder="如 CAND-001" /></el-form-item><el-form-item label="候选点名称" prop="site_name"><el-input v-model="form.site_name" placeholder="请输入名称" /></el-form-item><el-form-item label="区域编码" prop="region_code"><el-input v-model="form.region_code" placeholder="如 CA-06037" /></el-form-item><el-form-item label="城市"><el-input v-model="form.city" /></el-form-item><el-form-item label="纬度" prop="latitude"><el-input-number v-model="form.latitude" :precision="6" :step="0.0001" controls-position="right" /></el-form-item><el-form-item label="经度" prop="longitude"><el-input-number v-model="form.longitude" :precision="6" :step="0.0001" controls-position="right" /></el-form-item><el-form-item label="预算（USD）"><el-input-number v-model="form.budget_usd" :min="0" :step="1000" controls-position="right" /></el-form-item><el-form-item label="电力容量（kW）"><el-input-number v-model="form.electric_capacity_kw" :min="0" :step="10" controls-position="right" /></el-form-item><el-form-item label="停车位"><el-input-number v-model="form.parking_spaces" :min="0" controls-position="right" /></el-form-item><el-form-item label="面积（㎡）"><el-input-number v-model="form.area_sqm" :min="0" controls-position="right" /></el-form-item><el-form-item label="交通指数"><el-input-number v-model="form.traffic_index" :min="0" :step="0.01" controls-position="right" /></el-form-item><el-form-item label="人口密度"><el-input-number v-model="form.population_density" :min="0" :step="1" controls-position="right" /></el-form-item><el-form-item label="计划开放日期"><el-date-picker v-model="form.planned_open_date" type="date" value-format="YYYY-MM-DD" /></el-form-item><el-form-item label="数据截至日期"><el-date-picker v-model="form.data_as_of" type="date" value-format="YYYY-MM-DD" /></el-form-item><el-form-item label="生命周期"><el-select v-model="form.lifecycle_status"><el-option label="草稿" value="DRAFT" /><el-option label="待审核" value="REVIEW" /></el-select></el-form-item></div></el-form><template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" @click="saveCandidate">保存候选站点</el-button></template></el-dialog>
  </section>
</template>

