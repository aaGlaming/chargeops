<script setup lang="ts">
import { computed, onMounted, reactive, shallowRef, watch } from 'vue'
import { ElMessage, type UploadFile } from 'element-plus'
import { Delete, Document, Download, Refresh, Search, UploadFilled } from '@element-plus/icons-vue'
import { getApiError } from '../api/http'
import { useAuth } from '../stores/auth'
import { getChunkPreview, getRagDocument, listChunkBatches, listEmbeddingBatches, listRagDocuments, previewRagChunks, retryRagDocument, searchRag, uploadRagDocument, embedRagDocument, rebuildRagEmbedding, type ChunkBatch, type ChunkBatchResponse, type EmbeddingBatch, type RagDocument, type RagDocumentDetail, type RagHit, type RagSearchResponse } from '../api/rag'

const auth = useAuth()
const canWrite = computed(() => auth.hasPermission('rag.write'))
const activeTab = shallowRef<'documents' | 'chunks' | 'search'>('documents')
const documents = shallowRef<RagDocument[]>([])
const selectedDocument = shallowRef<RagDocumentDetail | null>(null)
const chunkBatches = shallowRef<ChunkBatch[]>([])
const chunkPreview = shallowRef<ChunkBatchResponse | null>(null)
const embeddingBatches = shallowRef<EmbeddingBatch[]>([])
const selectedEmbedding = shallowRef<EmbeddingBatch | null>(null)
const selectedHit = shallowRef<RagHit | null>(null)
const hitDrawerVisible = shallowRef(false)
const selectedChunk = shallowRef<ChunkBatchResponse['chunks'][number] | null>(null)
const searchResult = shallowRef<RagSearchResponse | null>(null)
const loading = shallowRef(false)
const detailLoading = shallowRef(false)
const uploadLoading = shallowRef(false)
const chunkLoading = shallowRef(false)
const embeddingLoading = shallowRef(false)
const searchLoading = shallowRef(false)
const uploadProgress = shallowRef(0)
const errorMessage = shallowRef('')
const traceId = shallowRef('')
const uploadFile = shallowRef<File | null>(null)
const uploadForm = reactive({ title: '', doc_type: 'business_rule', source_type: 'user_upload', source_url: '', region_code: '', version: 'latest', effective_date: '' })
const filters = reactive({ doc_type: '', parse_status: '', vector_status: '', region_code: '' })
const chunkForm = reactive({ targetTokens: 800, overlapTokens: 120 })
const searchForm = reactive({ query: '', top_k: 5, doc_type: '', region_code: '', version: '', agent_scenario: '', use_vector: true, use_keyword: true, use_rerank: false })

const documentStatus = computed(() => selectedDocument.value ? `${selectedDocument.value.parse_status} · ${selectedDocument.value.vector_status}` : '未选择文档')

function sourceLabel(value: string) { return ({ public: '公开', user_upload: '上传', synthetic: '合成', agent: 'Agent' } as Record<string, string>)[value] || value }
function statusType(value: string) { const normalized = value.toUpperCase(); if (normalized.includes('FAILED') || normalized.includes('ERROR') || normalized.includes('INVALID')) return 'danger'; if (normalized.includes('PENDING') || normalized.includes('RUNNING') || normalized.includes('PREVIEW')) return 'warning'; if (normalized.includes('INDEXED') || normalized.includes('PARSED') || normalized.includes('GENERATED') || normalized.includes('SUCCESS')) return 'success'; return 'info' }
function pretty(value: unknown) { return JSON.stringify(value, null, 2) }

async function loadDocuments() {
  loading.value = true
  errorMessage.value = ''
  try { documents.value = (await listRagDocuments({ doc_type: filters.doc_type || undefined, parse_status: filters.parse_status || undefined, vector_status: filters.vector_status || undefined, region_code: filters.region_code || undefined, page: 1, page_size: 200 })).items } catch (error) { const detail = getApiError(error); errorMessage.value = detail.message; traceId.value = detail.traceId } finally { loading.value = false }
}

async function selectDocument(document: RagDocument) {
  selectedDocument.value = document as RagDocumentDetail
  activeTab.value = 'chunks'
  detailLoading.value = true
  errorMessage.value = ''
  try {
    const [detail, batches, embeddings] = await Promise.all([getRagDocument(document.id), listChunkBatches(document.id), listEmbeddingBatches(document.id)])
    selectedDocument.value = detail
    chunkBatches.value = batches.items
    embeddingBatches.value = embeddings.items
    selectedEmbedding.value = embeddings.items[0] || null
    if (batches.items[0]) chunkPreview.value = await getChunkPreview(document.id, batches.items[0].batch_key)
  } catch (error) { const detail = getApiError(error); errorMessage.value = detail.message; traceId.value = detail.traceId } finally { detailLoading.value = false }
}

function handleUploadChange(file: UploadFile) { uploadFile.value = file.raw || null }

async function uploadDocument() {
  if (!canWrite.value || !uploadFile.value) { ElMessage.warning('请选择 Markdown 文件，并确认当前账号拥有 RAG 写入权限。'); return }
  uploadLoading.value = true
  uploadProgress.value = 0
  try {
    const response = await uploadRagDocument(uploadFile.value, uploadForm, (value) => { uploadProgress.value = value })
    ElMessage.success(response.duplicate ? '文档已存在，已加载现有版本。' : 'Markdown 文档上传并解析完成。')
    uploadFile.value = null
    await loadDocuments()
    await selectDocument(response.document)
  } catch (error) { ElMessage.error(getApiError(error).message) } finally { uploadLoading.value = false }
}

async function retryParse() {
  if (!selectedDocument.value || !canWrite.value) return
  detailLoading.value = true
  try { selectedDocument.value = await retryRagDocument(selectedDocument.value.id); await loadDocuments(); ElMessage.success('文档解析已重试。') } catch (error) { ElMessage.error(getApiError(error).message) } finally { detailLoading.value = false }
}

async function generateChunks(rebuild: boolean) {
  if (!selectedDocument.value || !canWrite.value) return
  chunkLoading.value = true
  try { chunkPreview.value = await previewRagChunks(selectedDocument.value.id, chunkForm.targetTokens, chunkForm.overlapTokens, rebuild); chunkBatches.value = [chunkPreview.value.batch, ...chunkBatches.value.filter((batch) => batch.batch_key !== chunkPreview.value?.batch.batch_key)]; ElMessage.success(rebuild ? 'Chunk 已重建并保留历史批次。' : 'Chunk 预览已生成。') } catch (error) { ElMessage.error(getApiError(error).message) } finally { chunkLoading.value = false }
}

async function showChunkBatch(batch: ChunkBatch) {
  if (!selectedDocument.value) return
  chunkLoading.value = true
  try { chunkPreview.value = await getChunkPreview(selectedDocument.value.id, batch.batch_key) } catch (error) { ElMessage.error(getApiError(error).message) } finally { chunkLoading.value = false }
}

async function embedDocument(rebuild = false) {
  if (!selectedDocument.value || !canWrite.value) return
  embeddingLoading.value = true
  try { const response = rebuild ? await rebuildRagEmbedding(selectedDocument.value.id, chunkPreview.value?.batch.batch_key) : await embedRagDocument(selectedDocument.value.id, chunkPreview.value?.batch.batch_key); selectedEmbedding.value = response.batch; embeddingBatches.value = [response.batch, ...embeddingBatches.value.filter((batch) => batch.batch_key !== response.batch.batch_key)]; await loadDocuments(); ElMessage.success('Embedding 批次已提交。') } catch (error) { ElMessage.error(getApiError(error).message) } finally { embeddingLoading.value = false }
}

async function runSearch() {
  if (!searchForm.query.trim()) { ElMessage.warning('请输入检索问题。'); return }
  searchLoading.value = true
  try { searchResult.value = await searchRag({ query: searchForm.query, top_k: searchForm.top_k, doc_type: searchForm.doc_type || undefined, region_code: searchForm.region_code || undefined, version: searchForm.version || undefined, agent_scenario: searchForm.agent_scenario || undefined, use_vector: searchForm.use_vector, use_keyword: searchForm.use_keyword, use_rerank: searchForm.use_rerank }); activeTab.value = 'search' } catch (error) { const detail = getApiError(error); errorMessage.value = detail.message; traceId.value = detail.traceId } finally { searchLoading.value = false }
}

function openOriginal(hit: RagHit) { selectedHit.value = hit; hitDrawerVisible.value = true }

watch(() => [filters.doc_type, filters.parse_status, filters.vector_status, filters.region_code], loadDocuments)
onMounted(loadDocuments)
</script>

<template>
  <section class="rag-page">
    <div class="rag-header"><div><span class="eyebrow">RETRIEVAL AUGMENTED GENERATION</span><h2>RAG 知识库工作台</h2><p>从 Markdown 原文、结构化 Chunk、向量索引到带原文位置的检索证据。</p></div><div class="rag-header-status"><el-tag type="success" effect="plain">MySQL 元数据</el-tag><el-tag type="success" effect="plain">Chroma 向量</el-tag></div></div>
    <el-alert v-if="errorMessage" class="page-alert" type="error" :closable="false" show-icon :title="errorMessage"><template #default><span v-if="traceId">trace_id: {{ traceId }}</span><el-button text type="primary" @click="loadDocuments">重试</el-button></template></el-alert>
    <el-tabs v-model="activeTab" class="rag-tabs">
      <el-tab-pane name="documents"><template #label><span><el-icon><Document /></el-icon> 文档与上传</span></template>
        <div class="rag-doc-layout"><div class="rag-doc-list-column"><el-card class="rag-card"><template #header><div class="card-header"><div><strong>文档列表</strong><small>筛选版本、来源和解析/向量状态</small></div><el-tag type="info" effect="plain">{{ documents.length }}</el-tag></div></template><div class="rag-filter-row"><el-select v-model="filters.doc_type" clearable placeholder="文档类型"><el-option label="业务规则" value="business_rule" /><el-option label="建设规范" value="construction_standard" /><el-option label="区域政策" value="regional_policy" /><el-option label="补贴政策" value="subsidy_policy" /></el-select><el-select v-model="filters.parse_status" clearable placeholder="解析状态"><el-option label="已解析" value="PARSED" /><el-option label="失败" value="FAILED" /><el-option label="处理中" value="PARSING" /></el-select><el-select v-model="filters.vector_status" clearable placeholder="向量状态"><el-option label="已索引" value="INDEXED" /><el-option label="待处理" value="PENDING" /><el-option label="失败" value="FAILED" /></el-select><el-input v-model="filters.region_code" clearable placeholder="区域编码" /></div><el-table v-loading="loading" :data="documents" size="small" height="500" empty-text="暂无 RAG 文档" @row-click="(row: RagDocument) => selectDocument(row)"><el-table-column label="文档" min-width="190"><template #default="scope"><div class="station-name-cell"><strong>{{ scope.row.title }}</strong><small>{{ scope.row.document_key }}</small></div></template></el-table-column><el-table-column prop="version" label="版本" width="80" /><el-table-column label="来源" width="74"><template #default="scope"><el-tag size="small" effect="plain">{{ sourceLabel(scope.row.source_type) }}</el-tag></template></el-table-column><el-table-column label="解析" width="80"><template #default="scope"><el-tag size="small" :type="statusType(scope.row.parse_status)">{{ scope.row.parse_status }}</el-tag></template></el-table-column><el-table-column label="向量" width="80"><template #default="scope"><el-tag size="small" :type="statusType(scope.row.vector_status)">{{ scope.row.vector_status }}</el-tag></template></el-table-column><el-table-column prop="chunk_count" label="Chunks" width="72" /></el-table></el-card></div>
          <div class="rag-upload-column"><el-card class="rag-card"><template #header><div class="card-header"><div><strong>上传 Markdown</strong><small>解析状态和原始文件会保留</small></div><el-tag v-if="!canWrite" type="warning" effect="plain">只读</el-tag></div></template><el-upload class="rag-upload-zone" drag :auto-upload="false" :show-file-list="false" accept=".md,.markdown,.txt" :on-change="handleUploadChange"><el-icon class="el-icon--upload"><UploadFilled /></el-icon><div class="el-upload__text">拖入 Markdown，或 <em>点击选择</em></div><div class="el-upload__tip">UTF-8，支持标题、列表、表格、条款和代码围栏</div></el-upload><div v-if="uploadFile" class="rag-selected-file"><el-icon><Document /></el-icon><strong>{{ uploadFile.name }}</strong><el-button text type="danger" @click="uploadFile = null"><el-icon><Delete /></el-icon></el-button></div><el-form label-position="top" class="rag-upload-form"><el-form-item label="标题"><el-input v-model="uploadForm.title" placeholder="可留空，默认使用文件名" /></el-form-item><div class="form-grid form-grid--two"><el-form-item label="文档类型"><el-select v-model="uploadForm.doc_type"><el-option label="业务规则" value="business_rule" /><el-option label="建设规范" value="construction_standard" /><el-option label="区域政策" value="regional_policy" /><el-option label="补贴政策" value="subsidy_policy" /></el-select></el-form-item><el-form-item label="版本"><el-input v-model="uploadForm.version" /></el-form-item><el-form-item label="区域编码"><el-input v-model="uploadForm.region_code" placeholder="可选" /></el-form-item><el-form-item label="生效日期"><el-date-picker v-model="uploadForm.effective_date" type="date" value-format="YYYY-MM-DD" /></el-form-item></div><el-form-item label="来源 URL"><el-input v-model="uploadForm.source_url" placeholder="可选" /></el-form-item><el-progress v-if="uploadLoading" :percentage="uploadProgress" /><el-button type="primary" :loading="uploadLoading" :disabled="!canWrite || !uploadFile" @click="uploadDocument"><el-icon><UploadFilled /></el-icon>上传并解析</el-button></el-form></el-card><el-card v-if="selectedDocument" class="rag-card"><template #header><div class="card-header"><div><strong>解析状态</strong><small>{{ selectedDocument.title }}</small></div><el-tag :type="statusType(documentStatus)">{{ documentStatus }}</el-tag></div></template><div class="parse-summary"><div><span>区块</span><strong>{{ selectedDocument.section_count }}</strong></div><div><span>Chunks</span><strong>{{ selectedDocument.chunk_count }}</strong></div><div><span>版本</span><strong>{{ selectedDocument.version }}</strong></div></div><el-alert v-if="selectedDocument.parse_error" type="error" :closable="false" show-icon :title="selectedDocument.parse_error" /><el-button v-if="selectedDocument.parse_status === 'FAILED'" :disabled="!canWrite" @click="retryParse"><el-icon><Refresh /></el-icon>重试解析</el-button></el-card></div>
        </div>
      </el-tab-pane>
      <el-tab-pane name="chunks"><template #label><span><el-icon><Document /></el-icon> Chunk 与向量</span></template>
        <el-card class="rag-card"><template #header><div class="card-header"><div><strong>{{ selectedDocument?.title || '请选择文档' }}</strong><small>清洗、切块、历史批次与 Embedding 入库</small></div><div class="rag-header-actions"><el-tag v-if="selectedDocument" effect="plain">{{ selectedDocument.version }}</el-tag><el-button text @click="activeTab = 'documents'">返回文档</el-button></div></div></template><el-empty v-if="!selectedDocument" description="请先在文档列表选择一个文档" :image-size="68" /><template v-else><div class="chunk-control-row"><el-form-item label="目标 tokens"><el-input-number v-model="chunkForm.targetTokens" :min="64" :max="8192" :step="64" /></el-form-item><el-form-item label="重叠 tokens"><el-input-number v-model="chunkForm.overlapTokens" :min="0" :max="2048" :step="16" /></el-form-item><el-button :disabled="!canWrite" :loading="chunkLoading" @click="generateChunks(false)">预览切块</el-button><el-button type="primary" :disabled="!canWrite" :loading="chunkLoading" @click="generateChunks(true)">重建并保留批次</el-button><el-button type="success" :disabled="!canWrite || !chunkPreview" :loading="embeddingLoading" @click="embedDocument(false)">向量化当前批次</el-button><el-button :disabled="!canWrite || !chunkPreview" :loading="embeddingLoading" @click="embedDocument(true)">重建向量</el-button></div><div class="chunk-content-grid"><div><div class="subsection-title"><strong>Chunk 预览</strong><small>{{ chunkPreview?.chunks.length || 0 }} 条</small></div><el-table v-loading="chunkLoading" :data="chunkPreview?.chunks || []" size="small" height="430" @row-click="(row: any) => selectedChunk = row"><el-table-column prop="chunk_index" label="#" width="54" /><el-table-column prop="heading_path" label="标题路径" min-width="145" /><el-table-column label="内容" min-width="280"><template #default="scope"><span class="chunk-content-cell">{{ scope.row.content }}</span></template></el-table-column><el-table-column label="字符" width="100"><template #default="scope">{{ scope.row.start_char }}-{{ scope.row.end_char }}</template></el-table-column><el-table-column label="校验" width="75"><template #default="scope"><el-tag size="small" :type="scope.row.validation_status === 'VALID' ? 'success' : 'danger'">{{ scope.row.validation_status }}</el-tag></template></el-table-column></el-table></div><div class="chunk-side-panel"><div class="subsection-title"><strong>历史 Chunk 批次</strong><small>{{ chunkBatches.length }}</small></div><div class="batch-list"><button v-for="batch in chunkBatches" :key="batch.batch_key" type="button" class="batch-item" @click="showChunkBatch(batch)"><div><strong>{{ batch.batch_key.slice(0, 18) }}</strong><small>{{ batch.target_tokens }} / {{ batch.overlap_tokens }} tokens</small></div><el-tag size="small" :type="statusType(batch.status)">{{ batch.status }}</el-tag></button></div><div v-if="selectedChunk" class="chunk-detail"><strong>原文片段</strong><small>{{ selectedChunk.original_href }}</small><p>{{ selectedChunk.content }}</p></div><div class="subsection-title embedding-title"><strong>Embedding 批次</strong><small>{{ embeddingBatches.length }}</small></div><div class="batch-list"><button v-for="batch in embeddingBatches" :key="batch.batch_key" type="button" class="batch-item" @click="selectedEmbedding = batch"><div><strong>{{ batch.embedding_model }}</strong><small>{{ batch.success_count }} 成功 · {{ batch.failed_count }} 失败</small></div><el-tag size="small" :type="statusType(batch.status)">{{ batch.status }}</el-tag></button></div><div v-if="selectedEmbedding" class="embedding-detail"><span>模型：{{ selectedEmbedding.embedding_model }}</span><span>请求：{{ selectedEmbedding.requested_count }} · 重试：{{ selectedEmbedding.pending_retry_count }}</span><p v-if="selectedEmbedding.error_message">{{ selectedEmbedding.error_message }}</p></div></div></div></template></el-card>
      </el-tab-pane>
      <el-tab-pane name="search"><template #label><span><el-icon><Search /></el-icon> 检索与调试</span></template>
        <div class="rag-search-layout"><el-card class="rag-card search-form-card"><template #header><div class="card-header"><div><strong>混合检索</strong><small>向量、关键词和可选重排</small></div></div></template><el-form label-position="top"><el-form-item label="问题"><el-input v-model="searchForm.query" type="textarea" :rows="4" placeholder="例如：加州 DC 快充建设有哪些补贴条件？" /></el-form-item><div class="form-grid form-grid--two"><el-form-item label="Top-K"><el-input-number v-model="searchForm.top_k" :min="1" :max="50" /></el-form-item><el-form-item label="文档类型"><el-select v-model="searchForm.doc_type" clearable placeholder="全部"><el-option label="区域政策" value="regional_policy" /><el-option label="补贴政策" value="subsidy_policy" /><el-option label="建设规范" value="construction_standard" /></el-select></el-form-item><el-form-item label="区域"><el-input v-model="searchForm.region_code" clearable /></el-form-item><el-form-item label="版本"><el-input v-model="searchForm.version" clearable /></el-form-item></div><el-form-item label="Agent 场景"><el-input v-model="searchForm.agent_scenario" clearable placeholder="可选，例如 policy_matching" /></el-form-item><el-checkbox v-model="searchForm.use_vector">向量召回</el-checkbox><el-checkbox v-model="searchForm.use_keyword">关键词召回</el-checkbox><el-checkbox v-model="searchForm.use_rerank">确定性重排</el-checkbox><el-button class="search-button" type="primary" :loading="searchLoading" @click="runSearch"><el-icon><Search /></el-icon>开始检索</el-button></el-form></el-card><div class="rag-search-result-column"><el-card class="rag-card"><template #header><div class="card-header"><div><strong>检索结果</strong><small>{{ searchResult ? `${searchResult.status} · ${searchResult.hits.length} 条命中` : '输入查询后展示结果' }}</small></div><el-tag v-if="searchResult" :type="searchResult.status === 'HIT' ? 'success' : 'warning'">{{ searchResult.status }}</el-tag></div></template><el-empty v-if="!searchResult" description="暂无检索结果" :image-size="62" /><template v-else><el-alert v-for="warning in searchResult.warnings" :key="warning" class="search-warning" type="warning" :closable="false" :title="warning" /><el-empty v-if="!searchResult.hits.length" description="没有找到可回溯证据" :image-size="58" /><div v-else class="search-hit-list"><button v-for="hit in searchResult.hits" :key="hit.chunk_id" type="button" class="search-hit" @click="openOriginal(hit)"><div class="search-hit-heading"><div><el-tag size="small" type="success" effect="plain">{{ hit.doc_type }}</el-tag><strong>{{ hit.title }}</strong></div><span>{{ hit.score.toFixed(3) }}</span></div><p>{{ hit.content }}</p><small>{{ hit.version }} · {{ hit.region_code || '全局' }} · {{ hit.effective_date || '未标注' }} · Chunk {{ hit.chunk_index }} · {{ hit.match_sources.join(' + ') }}</small></button></div></template></el-card><el-card v-if="searchResult" class="rag-card debug-card"><template #header><div class="card-header"><div><strong>检索调试</strong><small>查询改写、召回、过滤和排序摘要</small></div><el-tag type="info" effect="plain">{{ searchResult.run_id.slice(0, 12) }}</el-tag></div></template><div class="debug-stats"><div><span>向量召回</span><strong>{{ searchResult.vector_count }}</strong></div><div><span>关键词召回</span><strong>{{ searchResult.keyword_count }}</strong></div><div><span>重排</span><strong>{{ searchResult.rerank_applied ? '已启用' : '未启用' }}</strong></div></div><div class="debug-block"><strong>改写查询</strong><p>{{ searchResult.rewritten_query }}</p></div><div class="debug-block"><strong>查询改写结构</strong><pre>{{ pretty(searchResult.query_rewrite) }}</pre></div><div class="debug-block"><strong>召回候选</strong><pre>{{ pretty(searchResult.hits.map((hit) => ({ chunk_id: hit.chunk_id, score: hit.score, match_sources: hit.match_sources }))) }}</pre></div><div class="debug-block"><strong>过滤条件</strong><pre>{{ pretty(searchResult.filters) }}</pre></div><div class="debug-block"><strong>去重与排序</strong><p>候选按 chunk_id 合并去重，综合向量/关键词分数后按 score 降序排序，最后截取 Top-K。</p></div><div class="debug-block"><strong>最终上下文</strong><pre>{{ searchResult.hits.map((hit, index) => `[${index + 1}] ${hit.title} / Chunk ${hit.chunk_index}\n${hit.content}`).join('\n\n---\n\n') }}</pre></div></el-card></div></div>
      </el-tab-pane>
    </el-tabs>
    <el-drawer v-model="hitDrawerVisible" title="原文片段" size="520px"><template v-if="selectedHit"><div class="hit-drawer"><div class="detail-hero"><div class="workspace-icon"><el-icon><Document /></el-icon></div><div><span class="eyebrow">{{ selectedHit.chunk_id }}</span><h2>{{ selectedHit.title }}</h2><p>{{ selectedHit.source_url || '无来源 URL' }}</p></div></div><el-descriptions :column="2" border size="small"><el-descriptions-item label="文档类型">{{ selectedHit.doc_type }}</el-descriptions-item><el-descriptions-item label="版本">{{ selectedHit.version }}</el-descriptions-item><el-descriptions-item label="区域">{{ selectedHit.region_code || '全局' }}</el-descriptions-item><el-descriptions-item label="分数">{{ selectedHit.score.toFixed(4) }}</el-descriptions-item><el-descriptions-item label="字符位置">{{ selectedHit.start_char }} - {{ selectedHit.end_char }}</el-descriptions-item><el-descriptions-item label="匹配来源">{{ selectedHit.match_sources.join(' + ') }}</el-descriptions-item></el-descriptions><div class="original-fragment"><strong>原文片段</strong><p>{{ selectedHit.original_fragment || selectedHit.content }}</p></div><el-button type="primary" plain @click="hitDrawerVisible = false">关闭</el-button></div></template></el-drawer>
  </section>
</template>

