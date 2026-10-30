# Step 15：实现文本清洗和 Chunk 预览

## 已完成内容

### 清洗和结构化切块

- 新增 `clean-v1` 文本清洗器，处理 BOM、不可见字符、控制字符、重复空白、异常换行和文档边缘重复页眉/页脚。
- 复用 Markdown 解析区块，按标题、条款、段落、列表、表格和代码围栏边界组装 Chunk。
- 默认目标长度为 800 tokens，重叠长度为 120 tokens；接口允许在 64–8192 tokens 范围内调整。
- 采用确定性的字符估算（约 4 字符/token），待 Embedding 模型接入后可替换为真实 tokenizer。

### 批次、元数据和质量校验

- 新增 `rag_chunk_batch`，每次预览或重建都生成新的批次，历史批次和 Chunk 不覆盖。
- Chunk 保存批次、Chunk ID、序号、标题层级、文档版本、字符起止位置、清洗版本、目标参数和校验结果。
- 校验空 Chunk、超出目标长度、缺失标题层级和条款编号丢失，并在 `validation_issues` 返回原因。
- `original_href` 携带文档 ID 和字符起止位置，前端可据此打开原文片段。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/rag/documents/{document_id}/chunks/preview` | 使用参数清洗并生成预览批次 |
| `GET` | `/rag/documents/{document_id}/chunks/preview?batch_key=...` | 查看指定批次；不传参数查看最新批次 |
| `POST` | `/rag/documents/{document_id}/chunks/rebuild` | 使用新参数重新切块，保留旧批次 |
| `GET` | `/rag/documents/{document_id}/chunks/batches` | 查看文档的历史切块批次 |
| `GET` | `/rag/documents/{document_id}/source?start_char=...&end_char=...` | 按 Chunk 字符位置读取原文片段 |

写接口需要 `rag.write`，读接口需要 `rag.read`。向量状态继续保持 `PENDING`，向量化在 Step 16 处理。

## 数据库迁移

- `rag_chunk` 增加可空 `batch_id`，兼容 Step 5–14 已有 Chunk。
- 新增 `rag_chunk_batch` 表，记录参数、文档版本、状态、Chunk 数、无效数和创建人。
- 记录迁移版本 `004_rag_chunk_batches`。

## 验证记录

- 数据库初始化后表总数为 26，迁移记录包含 `004_rag_chunk_batches`。
- 上传包含标题、编号条款、列表、表格和长段落的 Markdown，预览和重建均返回 200。
- 修改目标长度和重叠长度后生成不同批次，历史批次接口返回 2 个批次，旧 Chunk 保留。
- 返回 Chunk 的标题、版本、字符位置、预估 token 数、校验状态、问题列表和原文跳转地址。
- `compileall`、`ruff check backend/app --select F` 和 `git diff --check` 通过。

## 产物

- `backend/app/services/rag_chunks.py`
- `backend/app/schemas/rag.py`
- `backend/app/api/routes/rag.py`
- `infra/mysql/001_initial_schema.sql`
- `scripts/init_database.py`

**状态：完成。**
