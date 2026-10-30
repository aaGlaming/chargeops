# Step 14：实现 RAG 文档上传和 Markdown 解析

## 目标

实现 Markdown 文档上传、文件安全校验、元数据登记、SHA-256 去重、结构化解析、失败记录和重试，为后续切 Chunk 与向量化提供稳定输入。

## 已完成内容

### 上传和文件校验

- `POST /rag/documents` 使用 `multipart/form-data` 接收 Markdown 文件和文档元数据。
- 只接受 `.md` 扩展名、UTF-8 文本和允许的文本内容类型。
- 拒绝目录穿越、控制字符、超长文件名和超过 `RAG_MAX_FILE_SIZE_MB` 的文件。
- 默认上传目录为 `data/raw/user_upload/rag`，文件按文档键隔离保存。
- 记录文件 SHA-256、标题、文档类型、来源类型、来源 URL、区域、版本和生效日期。

### 去重和版本

- 同一 SHA-256 的文件返回已有文档，HTTP 200，并标记 `duplicate=true`。
- 文档键冲突返回 400，要求使用新的版本或文档键。
- 原始文件保留在本地，MySQL 保存相对路径和元数据。

### Markdown 解析

- 清理 BOM、Windows 换行、不可见控制字符和多余空行。
- 识别标题、段落、列表项、编号条款、Markdown 表格和代码围栏。
- 保存标题层级路径、区块类型、区块序号、字符起止位置、行号元数据和原文内容。
- 解析结果写入 `rag_document_section`，后续 Step 15 可据此切 Chunk。

### 状态和重试

- 文档状态：`PARSING`、`PARSED`、`FAILED`。
- 解析失败时写入 `parse_error`，保留原文件和文档元数据。
- `POST /rag/documents/{document_id}/retry` 重新读取原文件并执行解析。
- 上传、重复文件、解析成功、解析失败和重试事件写入审计日志。
- 向量状态保持 `PENDING`，向量化在 Step 16 处理。

## 数据库迁移

- 新增 `rag_document_section` 表。
- 为早期 `rag_document` 兼容表补充 `chunk_count`、`uploaded_by`、`deleted_at` 和 `parse_error`。
- 为早期 `rag_chunk` 兼容表补充 `heading_path`、`chroma_collection` 和 `metadata`。
- 记录迁移版本 `003_rag_document_sections`。

## 权限和接口

- 文档列表和详情需要 `rag.read`。
- 文档上传和解析重试需要 `rag.write`。

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/rag/documents` | 上传并解析 Markdown |
| `GET` | `/rag/documents` | 按类型、解析状态、向量状态和区域分页查询 |
| `GET` | `/rag/documents/{document_id}` | 查看文档元数据和解析区块 |
| `POST` | `/rag/documents/{document_id}/retry` | 重试 Markdown 解析 |

## 验证记录

- 数据库迁移后表总数为 25，保留原有 2 条公开 RAG 文档。
- 上传包含标题、编号条款、表格和列表的 Markdown，HTTP 201，解析状态为 `PARSED`。
- 详情接口返回解析区块和标题路径。
- 重复上传同一内容返回 HTTP 200、`duplicate=true`。
- 空 Markdown 上传后记录 `FAILED` 和 `parse_error`；修复原文件后重试返回 `PARSED`。
- 非 Markdown 文件返回 HTTP 400 `INVALID_RAG_DOCUMENT`。
- 测试文档、文件和测试账号已清理。

## 产物

- `backend/app/schemas/rag.py`
- `backend/app/services/rag_documents.py`
- `backend/app/api/routes/rag.py`
- `infra/mysql/001_initial_schema.sql`
- `scripts/init_database.py`

