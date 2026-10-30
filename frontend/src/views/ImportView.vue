<script setup lang="ts">
import { computed, onMounted, reactive, shallowRef, watch } from 'vue'
import { ElMessage, ElMessageBox, type UploadFile } from 'element-plus'
import { Download, DocumentChecked, Refresh, UploadFilled } from '@element-plus/icons-vue'
import { useAuth } from '../stores/auth'
import { useNotifications } from '../composables/useNotifications'
import { createImportBatch, getImportBatch, listImportBatches, rollbackImportBatch } from '../api/imports'
import { getApiError } from '../api/http'

type DatasetKey = 'stations' | 'connectors' | 'metrics' | 'faults' | 'candidates' | 'expansion'
type FieldKind = 'text' | 'number' | 'date' | 'datetime'
type ValidationLevel = 'error' | 'warning'

interface FieldDefinition {
  key: string
  label: string
  kind: FieldKind
  required?: boolean
  hint: string
}

interface DatasetDefinition {
  key: DatasetKey
  label: string
  description: string
  accept: string
  templateName: string
  fields: FieldDefinition[]
}

interface ValidationError {
  row: number
  field: string
  level: ValidationLevel
  message: string
  suggestion: string
}

interface ImportBatch {
  id: string
  dataset: string
  fileName: string
  createdAt: string
  status: 'PENDING' | 'IMPORTED' | 'PARTIAL' | 'FAILED' | 'ROLLED_BACK'
  rollbackStatus: 'NOT_REQUESTED' | 'ROLLED_BACK'
  rowCount: number
  successCount: number
  failedCount: number
  skippedCount: number
  dataVersion: string
  errors?: Array<Record<string, unknown>>
}

const DATASETS: Record<DatasetKey, DatasetDefinition> = {
  stations: {
    key: 'stations', label: '站点', description: '充电站主数据、坐标、访问类型和容量', accept: '.csv,.json,.geojson', templateName: 'stations_template.csv',
    fields: [
      { key: 'external_station_id', label: '外部站点 ID', kind: 'text', required: true, hint: '业务系统或公开数据的稳定站点标识' },
      { key: 'station_name', label: '站点名称', kind: 'text', required: true, hint: '站点展示名称' },
      { key: 'latitude', label: '纬度', kind: 'number', required: true, hint: '-90 到 90' },
      { key: 'longitude', label: '经度', kind: 'number', required: true, hint: '-180 到 180' },
      { key: 'station_status', label: '站点状态', kind: 'text', required: true, hint: '如 E、P、暂不可用' },
      { key: 'access_type', label: '访问类型', kind: 'text', required: true, hint: 'PUBLIC、PRIVATE 或 UNKNOWN' },
      { key: 'data_version', label: '数据版本', kind: 'text', required: true, hint: '例如 2026-10-30' },
    ],
  },
  connectors: {
    key: 'connectors', label: '连接器', description: '站点连接器类型、数量、功率和状态', accept: '.csv,.json', templateName: 'connectors_template.csv',
    fields: [
      { key: 'station_external_id', label: '外部站点 ID', kind: 'text', required: true, hint: '必须匹配已存在的站点' },
      { key: 'connector_type', label: '连接器类型', kind: 'text', required: true, hint: '如 CCS、CHAdeMO、J1772' },
      { key: 'quantity', label: '数量', kind: 'number', required: true, hint: '非负整数' },
      { key: 'power_kw', label: '功率（kW）', kind: 'number', hint: '可选，非负数' },
      { key: 'connector_status', label: '连接器状态', kind: 'text', hint: '可用、维护中或 UNKNOWN' },
      { key: 'data_version', label: '数据版本', kind: 'text', required: true, hint: '例如 2026-10-30' },
    ],
  },
  metrics: {
    key: 'metrics', label: '运营指标', description: '站点日/小时会话量、能耗和利用率', accept: '.csv,.json', templateName: 'station_metrics_template.csv',
    fields: [
      { key: 'station_external_id', label: '外部站点 ID', kind: 'text', required: true, hint: '必须匹配已存在的站点' },
      { key: 'metric_date', label: '指标日期', kind: 'date', required: true, hint: 'YYYY-MM-DD' },
      { key: 'metric_hour', label: '小时', kind: 'number', hint: '0 到 23，可为空表示日汇总' },
      { key: 'charging_sessions', label: '充电会话数', kind: 'number', hint: '非负整数' },
      { key: 'energy_kwh', label: '能耗（kWh）', kind: 'number', hint: '非负数' },
      { key: 'occupancy_rate', label: '利用率', kind: 'number', hint: '0 到 1 或百分比' },
      { key: 'data_as_of', label: '数据截至日期', kind: 'date', hint: 'YYYY-MM-DD' },
    ],
  },
  faults: {
    key: 'faults', label: '故障事件', description: '站点故障、严重等级和恢复信息', accept: '.csv,.json', templateName: 'station_faults_template.csv',
    fields: [
      { key: 'station_external_id', label: '外部站点 ID', kind: 'text', required: true, hint: '必须匹配已存在的站点' },
      { key: 'fault_type', label: '故障类型', kind: 'text', required: true, hint: '如 connector、power、network' },
      { key: 'severity', label: '严重等级', kind: 'text', required: true, hint: 'LOW、MEDIUM、HIGH、CRITICAL' },
      { key: 'started_at', label: '开始时间', kind: 'datetime', required: true, hint: 'ISO 8601 时间' },
      { key: 'recovered_at', label: '恢复时间', kind: 'datetime', hint: '可为空' },
      { key: 'status', label: '状态', kind: 'text', hint: 'OPEN、RECOVERED、CLOSED' },
    ],
  },
  candidates: {
    key: 'candidates', label: '候选站点', description: '候选点坐标、建设条件和交通人口指标', accept: '.csv,.json,.geojson', templateName: 'candidate_sites_template.csv',
    fields: [
      { key: 'candidate_site_external_id', label: '外部候选点 ID', kind: 'text', required: true, hint: '稳定的候选点标识' },
      { key: 'site_name', label: '候选点名称', kind: 'text', required: true, hint: '站点规划名称' },
      { key: 'region_code', label: '区域编码', kind: 'text', required: true, hint: '例如 CA-06037' },
      { key: 'latitude', label: '纬度', kind: 'number', required: true, hint: '-90 到 90' },
      { key: 'longitude', label: '经度', kind: 'number', required: true, hint: '-180 到 180' },
      { key: 'budget_usd', label: '预算（USD）', kind: 'number', hint: '非负数' },
      { key: 'data_as_of', label: '数据截至日期', kind: 'date', hint: 'YYYY-MM-DD' },
    ],
  },
  expansion: {
    key: 'expansion', label: '扩容案例', description: '既有容量、利用率、故障和扩容建议', accept: '.csv,.json', templateName: 'expansion_cases_template.csv',
    fields: [
      { key: 'case_external_id', label: '案例 ID', kind: 'text', required: true, hint: '稳定的扩容案例标识' },
      { key: 'station_external_id', label: '外部站点 ID', kind: 'text', required: true, hint: '必须匹配已存在的站点' },
      { key: 'case_date', label: '案例日期', kind: 'date', required: true, hint: 'YYYY-MM-DD' },
      { key: 'peak_occupancy_rate', label: '峰值利用率', kind: 'number', hint: '0 到 1 或百分比' },
      { key: 'requested_budget_usd', label: '申请预算（USD）', kind: 'number', hint: '非负数' },
      { key: 'proposed_fast_connectors', label: '建议快充数', kind: 'number', hint: '非负整数' },
      { key: 'priority', label: '优先级', kind: 'text', required: true, hint: 'LOW、MEDIUM、HIGH、CRITICAL' },
    ],
  },
}

const auth = useAuth()
const { notify } = useNotifications()
const selectedDataset = shallowRef<DatasetKey>('stations')
const selectedConfig = computed(() => DATASETS[selectedDataset.value])
const activeStep = shallowRef(1)
const file = shallowRef<File | null>(null)
const rows = shallowRef<Record<string, string>[]>([])
const headers = shallowRef<string[]>([])
const mapping = reactive<Record<string, string>>({})
const validationErrors = shallowRef<ValidationError[]>([])
const parseError = shallowRef('')
const importing = shallowRef(false)
const progress = shallowRef(0)
const batches = shallowRef<ImportBatch[]>([])
const selectedBatch = shallowRef<ImportBatch | null>(null)
const batchDrawerVisible = shallowRef(false)

const mappedCount = computed(() => selectedConfig.value.fields.filter((field) => mapping[field.key]).length)
const requiredCount = computed(() => selectedConfig.value.fields.filter((field) => field.required).length)
const blockingErrorCount = computed(() => validationErrors.value.filter((item) => item.level === 'error').length)
const warningCount = computed(() => validationErrors.value.filter((item) => item.level === 'warning').length)
const previewRows = computed(() => rows.value.slice(0, 8))
const canConfirm = computed(() => Boolean(file.value && rows.value.length && mappedCount.value >= requiredCount.value && blockingErrorCount.value === 0 && !importing.value))
const canImport = computed(() => auth.hasPermission('import.write'))

function clearMapping() {
  Object.keys(mapping).forEach((key) => delete mapping[key])
}

function resetFileState() {
  file.value = null
  rows.value = []
  headers.value = []
  validationErrors.value = []
  parseError.value = ''
  activeStep.value = 1
  clearMapping()
}

function parseCsv(text: string) {
  const records: string[][] = []
  let record: string[] = []
  let cell = ''
  let quoted = false
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index]
    const next = text[index + 1]
    if (char === '"' && quoted && next === '"') { cell += '"'; index += 1; continue }
    if (char === '"') { quoted = !quoted; continue }
    if (char === ',' && !quoted) { record.push(cell.trim()); cell = ''; continue }
    if ((char === '\n' || char === '\r') && !quoted) {
      if (char === '\r' && next === '\n') index += 1
      record.push(cell.trim()); cell = ''
      if (record.some((item) => item !== '')) records.push(record)
      record = []
      continue
    }
    cell += char
  }
  if (cell || record.length) { record.push(cell.trim()); records.push(record) }
  const [headerRow = [], ...dataRows] = records
  const normalizedHeaders = headerRow.map((item) => item.replace(/^\uFEFF/, '').trim())
  return { headers: normalizedHeaders, rows: dataRows.filter((row) => row.some(Boolean)).map((row) => Object.fromEntries(normalizedHeaders.map((header, index) => [header, row[index] ?? '']))) }
}

function parseJson(text: string) {
  const payload = JSON.parse(text) as unknown
  if (Array.isArray(payload)) return payload as Record<string, unknown>[]
  if (payload && typeof payload === 'object' && 'features' in payload && Array.isArray((payload as { features?: unknown[] }).features)) {
    return ((payload as { features: Array<{ properties?: Record<string, unknown>; geometry?: { coordinates?: number[] } }> }).features).map((feature) => ({
      ...(feature.properties ?? {}),
      ...(feature.geometry?.coordinates ? { longitude: feature.geometry.coordinates[0], latitude: feature.geometry.coordinates[1] } : {}),
    }))
  }
  if (payload && typeof payload === 'object') return [payload as Record<string, unknown>]
  throw new Error('JSON 顶层必须是数组、对象或 GeoJSON FeatureCollection')
}

function setParsedRows(parsedHeaders: string[], parsedRows: Record<string, unknown>[]) {
  const normalizedRows = parsedRows.map((row) => Object.fromEntries(Object.entries(row).map(([key, value]) => [key, value == null ? '' : String(value)])))
  headers.value = parsedHeaders.length ? parsedHeaders : [...new Set(normalizedRows.flatMap((row) => Object.keys(row)))]
  rows.value = normalizedRows
  clearMapping()
  selectedConfig.value.fields.forEach((field) => {
    const exact = headers.value.find((header) => header === field.key)
    const loose = headers.value.find((header) => header.toLowerCase().replaceAll('-', '_').replaceAll(' ', '_') === field.key)
    if (exact || loose) mapping[field.key] = exact || loose || ''
  })
  activeStep.value = 2
  validateRows()
}

async function handleUploadChange(upload: UploadFile) {
  if (!upload.raw) return
  resetFileState()
  file.value = upload.raw
  try {
    const text = await upload.raw.text()
    const extension = upload.raw.name.toLowerCase().split('.').pop()
    if (extension === 'json' || extension === 'geojson') {
      const parsed = parseJson(text)
      setParsedRows([], parsed)
    } else {
      const parsed = parseCsv(text)
      setParsedRows(parsed.headers, parsed.rows)
    }
    notify(`已读取 ${rows.value.length} 行数据，字段映射可继续调整。`, { title: '文件预览就绪', type: 'success' })
  } catch (error) {
    parseError.value = error instanceof Error ? error.message : '文件解析失败，请检查格式。'
    activeStep.value = 1
  }
}

function validateRows() {
  const errors: ValidationError[] = []
  selectedConfig.value.fields.forEach((field) => {
    if (field.required && !mapping[field.key]) errors.push({ row: 0, field: field.label, level: 'error', message: '必填字段尚未映射', suggestion: `请选择对应的“${field.label}”源字段` })
  })
  rows.value.forEach((row, index) => {
    selectedConfig.value.fields.forEach((field) => {
      const source = mapping[field.key]
      const value = source ? String(row[source] ?? '').trim() : ''
      if (field.required && !value) errors.push({ row: index + 2, field: field.label, level: 'error', message: '必填值为空', suggestion: '补充字段值后重新上传' })
      if (!value) return
      if (field.kind === 'number' && Number.isNaN(Number(value))) errors.push({ row: index + 2, field: field.label, level: 'error', message: '应为数字', suggestion: '移除单位、千位分隔符或其他文本' })
      if (field.key === 'latitude' && (Number(value) < -90 || Number(value) > 90)) errors.push({ row: index + 2, field: field.label, level: 'error', message: '纬度超出范围', suggestion: '请输入 -90 到 90 之间的数值' })
      if (field.key === 'longitude' && (Number(value) < -180 || Number(value) > 180)) errors.push({ row: index + 2, field: field.label, level: 'error', message: '经度超出范围', suggestion: '请输入 -180 到 180 之间的数值' })
      if (field.key === 'occupancy_rate' || field.key === 'peak_occupancy_rate') {
        const rate = Number(value)
        if (rate < 0 || rate > 100) errors.push({ row: index + 2, field: field.label, level: 'warning', message: '利用率不是 0-100 范围', suggestion: '请确认是小数比例还是百分比' })
      }
      if ((field.kind === 'date' || field.kind === 'datetime') && Number.isNaN(Date.parse(value))) errors.push({ row: index + 2, field: field.label, level: 'error', message: '日期格式无法识别', suggestion: '使用 YYYY-MM-DD 或 ISO 8601 格式' })
    })
  })
  validationErrors.value = errors.slice(0, 500)
}

function downloadFile(name: string, content: string, type = 'text/csv;charset=utf-8') {
  const url = URL.createObjectURL(new Blob([content], { type }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  anchor.click()
  URL.revokeObjectURL(url)
}

function downloadTemplate(dataset: DatasetDefinition) {
  const header = dataset.fields.map((field) => field.key).join(',')
  downloadFile(dataset.templateName, `${header}\n`)
  notify(`已下载 ${dataset.label} 模板。`, { title: '模板下载', type: 'success' })
}

function downloadFailureReport() {
  const header = 'row,field,level,message,suggestion'
  const sourceErrors = selectedBatch.value?.errors?.length ? selectedBatch.value.errors.map((item) => ({ row: item.row || '', field: item.field || '', level: item.level || 'error', message: item.message || item.error_message || '', suggestion: item.suggestion || '修复该行后重新上传' })) : validationErrors.value
  const body = sourceErrors.map((item) => [item.row, item.field, item.level, item.message, item.suggestion].map((value) => `"${String(value).replaceAll('"', '""')}"`).join(',')).join('\n')
  downloadFile(`import-errors-${Date.now()}.csv`, `${header}\n${body}`)
}

async function confirmImport() {
  if (!canConfirm.value) {
    ElMessage.warning('请完成必填字段映射，并先修复阻断错误。')
    return
  }
  importing.value = true
  progress.value = 8
  try {
    const responsePromise = createImportBatch({ dataset_type: selectedDataset.value, file_name: file.value?.name || 'upload', data_version: findDataVersion(), mapping: { ...mapping }, rows: rows.value })
    for (const value of [28, 54, 76, 92]) {
      await new Promise((resolve) => window.setTimeout(resolve, 100))
      progress.value = value
    }
    const response = await responsePromise
    progress.value = 100
    const batch = fromApiBatch(response)
    batches.value = [batch, ...batches.value.filter((item) => item.id !== batch.id)]
    activeStep.value = 4
    window.dispatchEvent(new CustomEvent('chargeops:data-imported', { detail: batch }))
    notify(batch.status === 'PARTIAL' ? '批次已登记，但仍有失败行，请下载失败记录。' : '数据已完成导入，站点、列表、Agent 和驾驶舱可以读取最新批次。', { title: '导入完成', type: batch.status === 'PARTIAL' ? 'warning' : 'success', duration: 5000 })
  } catch (error) {
    const detail = getApiError(error)
    ElMessage.error(detail.traceId ? `${detail.message}（trace_id: ${detail.traceId}）` : detail.message)
  } finally {
    importing.value = false
  }
}

function fromApiBatch(batch: { id: number; dataset_type: string; source_file?: string | null; data_version: string; status: ImportBatch['status']; rollback_status: ImportBatch['rollbackStatus']; row_count: number; success_count: number; failed_count: number; skipped_count: number; created_at: string }): ImportBatch {
  return { id: String(batch.id), dataset: DATASETS[batch.dataset_type as DatasetKey]?.label || batch.dataset_type, fileName: batch.source_file || 'upload', createdAt: new Date(batch.created_at).toLocaleString('zh-CN', { hour12: false }), status: batch.status, rollbackStatus: batch.rollback_status, rowCount: batch.row_count, successCount: batch.success_count, failedCount: batch.failed_count, skippedCount: batch.skipped_count, dataVersion: batch.data_version }
}

function findDataVersion() {
  const field = mapping.data_version
  return field && rows.value[0]?.[field] ? rows.value[0][field] : new Date().toISOString().slice(0, 10)
}

async function openBatch(batch: ImportBatch) {
  selectedBatch.value = batch
  batchDrawerVisible.value = true
  if (/^\d+$/.test(batch.id)) {
    try {
      const detail = await getImportBatch(Number(batch.id))
      selectedBatch.value = { ...batch, errors: detail.errors || [] }
    } catch (error) {
      ElMessage.warning(getApiError(error).message)
    }
  }
}

async function rollbackBatch(batch: ImportBatch) {
  try {
    await ElMessageBox.confirm(`确认回滚批次 ${batch.id}？该操作会移除本批次关联数据。`, '回滚导入批次', { type: 'warning', confirmButtonText: '确认回滚', cancelButtonText: '取消' })
    if (/^\d+$/.test(batch.id)) await rollbackImportBatch(Number(batch.id))
    batch.status = 'ROLLED_BACK'
    batch.rollbackStatus = 'ROLLED_BACK'
    notify(`批次 ${batch.id} 已标记为回滚。`, { title: '回滚完成', type: 'success' })
  } catch {
    // 用户取消确认时不改变批次状态。
  }
}

function refreshDownstream() {
  window.dispatchEvent(new CustomEvent('chargeops:data-refresh-requested'))
  notify('已发出数据刷新通知，业务页面会在下一次查询时读取最新批次。', { title: '刷新请求已发送' })
}

watch(selectedDataset, resetFileState)
watch(() => JSON.stringify(mapping), validateRows)

onMounted(async () => {
  if (!canImport.value) return
  try {
    const response = await listImportBatches()
    batches.value = response.items.map(fromApiBatch)
  } catch {
    // Empty batch history is a valid first-use state; the next upload will show API errors explicitly.
  }
})
</script>

<template>
  <section class="import-page">
    <div v-if="!canImport" class="permission-state">
      <el-result icon="warning" title="没有数据导入权限" sub-title="请联系系统管理员申请 import.write 权限。" />
    </div>
    <template v-else>
      <div class="import-toolbar">
        <div class="import-toolbar-copy"><span class="eyebrow">DATA GOVERNANCE / INGESTION</span><strong>将业务数据安全地带入 ChargeOps</strong><small>文件先在浏览器中解析、预览和校验，确认后登记导入批次。</small></div>
        <el-button @click="refreshDownstream"><el-icon><Refresh /></el-icon>刷新业务数据</el-button>
      </div>

      <el-card class="import-step-card">
        <el-steps :active="activeStep - 1" finish-status="success" align-center>
          <el-step title="选择数据集" description="确定导入目标和模板" />
          <el-step title="上传与映射" description="预览文件并匹配字段" />
          <el-step title="校验与确认" description="检查错误并登记批次" />
          <el-step title="批次结果" description="查看统计或回滚" />
        </el-steps>
      </el-card>

      <div class="import-layout">
        <div class="import-main-column">
          <el-card v-if="activeStep === 1" class="import-card">
            <template #header><div class="card-header"><div><strong>选择要导入的数据集</strong><small>每次导入只处理一种业务数据，避免字段混用。</small></div><el-tag type="info" effect="plain">6 类模板</el-tag></div></template>
            <el-radio-group v-model="selectedDataset" class="dataset-grid">
              <label v-for="dataset in Object.values(DATASETS)" :key="dataset.key" class="dataset-option" :class="{ 'dataset-option--selected': selectedDataset === dataset.key }">
                <el-radio :value="dataset.key"><span class="dataset-label">{{ dataset.label }}</span></el-radio>
                <p>{{ dataset.description }}</p>
                <small>{{ dataset.accept.replaceAll(',', ' / ') }}</small>
              </label>
            </el-radio-group>
            <div class="template-downloads">
              <div><strong>模板下载</strong><span>模板包含字段名和数据类型提示，可直接用于准备上传文件。</span></div>
              <el-button v-for="dataset in Object.values(DATASETS)" :key="dataset.key" size="small" plain @click="downloadTemplate(dataset)"><el-icon><Download /></el-icon>{{ dataset.label }}</el-button>
            </div>
            <div class="import-actions"><el-button type="primary" @click="activeStep = 2">下一步：上传文件</el-button></div>
          </el-card>

          <el-card v-if="activeStep === 2" class="import-card">
            <template #header><div class="card-header"><div><strong>上传 {{ selectedConfig.label }}文件</strong><small>支持 {{ selectedConfig.accept.replaceAll(',', '、') }}，文件只在当前浏览器会话中预览。</small></div><el-button text @click="activeStep = 1">更换数据集</el-button></div></template>
            <el-upload class="drop-zone" drag :auto-upload="false" :show-file-list="false" :accept="selectedConfig.accept" :on-change="handleUploadChange">
              <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
              <div class="el-upload__text">将文件拖到这里，或 <em>点击选择</em></div>
              <template #tip><div class="el-upload__tip">CSV 首行应为字段名；JSON 使用对象数组；GeoJSON 使用 FeatureCollection。</div></template>
            </el-upload>
            <el-alert v-if="parseError" class="import-alert" type="error" :closable="false" :title="parseError" show-icon />
            <div v-if="file" class="selected-file"><el-icon><DocumentChecked /></el-icon><div><strong>{{ file.name }}</strong><small>{{ (file.size / 1024).toFixed(1) }} KB · {{ rows.length }} 行已读取</small></div><el-button text type="danger" @click="resetFileState">移除</el-button></div>
            <div class="import-actions"><el-button @click="activeStep = 1">上一步</el-button><el-button type="primary" :disabled="!file" @click="activeStep = 3">下一步：字段映射</el-button></div>
          </el-card>

          <el-card v-if="activeStep === 3" class="import-card">
            <template #header><div class="card-header"><div><strong>字段映射与校验</strong><small>已映射 {{ mappedCount }} / {{ selectedConfig.fields.length }} 个字段，预览前 8 行。</small></div><el-button text @click="activeStep = 2">重新上传</el-button></div></template>
            <el-table :data="selectedConfig.fields" size="small" class="mapping-table">
              <el-table-column label="目标字段" min-width="165"><template #default="scope"><strong>{{ scope.row.label }}</strong><el-tag v-if="scope.row.required" size="small" type="danger" effect="plain">必填</el-tag><small>{{ scope.row.key }}</small></template></el-table-column>
              <el-table-column label="类型" width="90"><template #default="scope"><el-tag size="small" effect="plain">{{ scope.row.kind }}</el-tag></template></el-table-column>
              <el-table-column label="源字段" min-width="180"><template #default="scope"><el-select v-model="mapping[scope.row.key]" clearable placeholder="选择字段" @change="validateRows"><el-option v-for="header in headers" :key="header" :label="header" :value="header" /></el-select></template></el-table-column>
              <el-table-column label="提示" min-width="210"><template #default="scope"><span class="field-hint">{{ scope.row.hint }}</span></template></el-table-column>
            </el-table>
            <div class="validation-summary"><div class="validation-stat validation-stat--error"><strong>{{ blockingErrorCount }}</strong><span>阻断错误</span></div><div class="validation-stat validation-stat--warning"><strong>{{ warningCount }}</strong><span>提示</span></div><div class="validation-stat"><strong>{{ rows.length }}</strong><span>待处理行</span></div><el-button v-if="validationErrors.length" text type="primary" @click="downloadFailureReport"><el-icon><Download /></el-icon>下载失败记录</el-button></div>
            <el-table :data="validationErrors" size="small" max-height="260" class="validation-table"><el-table-column prop="row" label="行号" width="72" /><el-table-column prop="field" label="字段" width="150" /><el-table-column label="级别" width="90"><template #default="scope"><el-tag size="small" :type="scope.row.level === 'error' ? 'danger' : 'warning'">{{ scope.row.level === 'error' ? '错误' : '提示' }}</el-tag></template></el-table-column><el-table-column prop="message" label="原因" min-width="180" /><el-table-column prop="suggestion" label="修复建议" min-width="230" /></el-table>
            <el-empty v-if="!validationErrors.length" class="validation-empty" description="当前没有发现字段错误" :image-size="56" />
            <div class="import-actions"><el-button @click="activeStep = 2">上一步</el-button><el-button type="primary" :loading="importing" :disabled="!canConfirm" @click="confirmImport">确认导入并登记批次</el-button></div>
          </el-card>

          <el-card v-if="activeStep === 4" class="import-card result-card">
            <el-result icon="success" title="导入批次已登记" sub-title="数据批次、成功数和失败记录已经保留，可在右侧批次列表查看详情。"><template #extra><el-button type="primary" @click="activeStep = 1">继续导入</el-button><el-button @click="refreshDownstream">刷新业务数据</el-button></template></el-result>
          </el-card>

          <el-card class="import-card preview-card">
            <template #header><div class="card-header"><div><strong>文件预览</strong><small>{{ previewRows.length ? `展示 ${previewRows.length} / ${rows.length} 行` : '上传文件后展示示例值' }}</small></div><el-tag v-if="file" effect="plain">{{ file.name }}</el-tag></div></template>
            <el-table v-if="previewRows.length" :data="previewRows" size="small" max-height="255"><el-table-column v-for="header in headers" :key="header" :prop="header" :label="header" min-width="145" show-overflow-tooltip /></el-table>
            <el-empty v-else description="暂无预览数据" :image-size="62" />
          </el-card>
        </div>

        <aside class="import-side-column">
          <el-card class="import-card batch-card">
            <template #header><div class="card-header"><div><strong>导入批次</strong><small>当前浏览器会话中的登记记录</small></div><el-tag type="info" effect="plain">{{ batches.length }}</el-tag></div></template>
            <el-empty v-if="!batches.length" description="暂无导入批次" :image-size="58" />
            <div v-else class="batch-list"><button v-for="batch in batches" :key="batch.id" class="batch-item" type="button" @click="openBatch(batch)"><div><strong>{{ batch.dataset }}</strong><small>{{ batch.fileName }}</small></div><div><el-tag size="small" :type="batch.status === 'IMPORTED' ? 'success' : batch.status === 'PARTIAL' ? 'warning' : 'info'">{{ batch.status }}</el-tag><small>{{ batch.successCount }}/{{ batch.rowCount }} 行</small></div></button></div>
          </el-card>
          <el-card class="import-card quality-card"><template #header><strong>导入质量规则</strong></template><ul><li>必填字段必须完成映射且不能为空。</li><li>坐标、数值和日期字段进行类型与范围校验。</li><li>错误行不会写入业务数据，可下载失败记录修复。</li><li>每次导入保留数据版本、源文件和批次标识。</li></ul></el-card>
        </aside>
      </div>

      <el-drawer v-model="batchDrawerVisible" title="导入批次详情" size="430px"><template v-if="selectedBatch"><div class="batch-detail"><div class="batch-detail-title"><span class="workspace-icon"><el-icon><DocumentChecked /></el-icon></span><div><span class="eyebrow">{{ selectedBatch.id }}</span><h3>{{ selectedBatch.dataset }}</h3><small>{{ selectedBatch.fileName }}</small></div></div><el-descriptions :column="1" border size="small"><el-descriptions-item label="状态">{{ selectedBatch.status }}</el-descriptions-item><el-descriptions-item label="数据版本">{{ selectedBatch.dataVersion }}</el-descriptions-item><el-descriptions-item label="总行数">{{ selectedBatch.rowCount }}</el-descriptions-item><el-descriptions-item label="成功行">{{ selectedBatch.successCount }}</el-descriptions-item><el-descriptions-item label="失败行">{{ selectedBatch.failedCount }}</el-descriptions-item><el-descriptions-item label="创建时间">{{ selectedBatch.createdAt }}</el-descriptions-item></el-descriptions><el-alert type="info" :closable="false" show-icon title="批次结果会关联到站点、列表、Agent 和驾驶舱的后续查询。" /><div class="drawer-actions"><el-button @click="downloadFailureReport">下载失败记录</el-button><el-button v-if="selectedBatch.rollbackStatus === 'NOT_REQUESTED'" type="danger" plain @click="rollbackBatch(selectedBatch)">回滚批次</el-button><el-tag v-else type="info">已回滚</el-tag></div></div></template></el-drawer>
    </template>
  </section>
</template>

