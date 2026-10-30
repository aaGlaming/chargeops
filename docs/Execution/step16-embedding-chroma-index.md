# Step 16：实现 Embedding 和 Chroma 入库

## 已完成内容

### Embedding 客户端

- 新增 OpenAI-compatible `POST /embeddings` 客户端。
- 支持批量输入、请求超时、指数退避重试和可选限流。
- Embedding 参数由配置控制：模型、批大小、超时、最大重试次数和每秒请求数。
- 返回数量、向量为空和响应格式异常都会记录为失败。

### Chroma 入库

- 通过 Chroma v2 HTTP API 获取或创建 collection，避免本地 Python 客户端与服务端配置格式不兼容。
- 使用显式 Embedding 向量写入，不依赖 Chroma 默认模型下载。
- Chroma metadata 保存 `chunk_id`、文档 ID、文档键、区域、文档类型、来源类型、版本、字符位置、Embedding 模型和批次 ID。
- Chroma 写入失败时删除本批次可能写入的 ID，并将对应 Item 标记为失败。

### 批次、失败和重试

- 新增 `rag_embedding_batch` 和 `rag_embedding_item`，保存模型、参数、批次状态、成功数、失败数、待重试数、尝试次数和错误详情。
- 同一文档、Chunk 批次和模型的重复请求幂等返回已存在批次；强制重建生成新批次。
- 支持单文档向量化、指定 Chunk 批次向量化、文档级删除重建和失败批次重试。
- 文档 `vector_status` 根据批次结果更新为 `INDEXED`、`PARTIAL`、`FAILED` 或 `PENDING`。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/rag/documents/{document_id}/embeddings` | 单文档向量化；可指定 `chunk_batch_key` |
| `POST` | `/rag/chunk-batches/{chunk_batch_key}/embeddings` | 指定 Chunk 批次向量化 |
| `POST` | `/rag/documents/{document_id}/embeddings/rebuild` | 删除文档现有向量并重建 |
| `GET` | `/rag/embedding-batches?document_id=...` | 查询向量化批次 |
| `GET` | `/rag/embedding-batches/{batch_id}` | 查询批次详情和 Item 状态 |
| `POST` | `/rag/embedding-batches/{batch_id}/retry` | 重试失败 Item |
| `DELETE` | `/rag/documents/{document_id}/embeddings?version=...` | 按文档版本删除向量 |

写接口需要 `rag.write`，查询接口需要 `rag.read`。

## 数据库迁移

- 新增 `rag_embedding_batch`：模型、参数、状态、计数、错误、时间和创建人。
- 新增 `rag_embedding_item`：Chunk 状态、尝试次数、向量维度和失败原因。
- 记录迁移版本 `005_rag_embedding_batches`。

## 验证记录

- 数据库初始化后表总数为 28，迁移记录包含 `005_rag_embedding_batches`。
- 使用本机 OpenAI-compatible Embedding 服务和 Chroma v2 服务完成公开文档向量化，返回 `COMPLETED`，Item 状态为 `INDEXED`，向量维度为 1024。
- 重复请求返回已有批次；文档级重建会删除旧 ID 并生成新批次。
- 上传测试 Markdown 后按 Chunk 批次向量化成功，并能通过字符位置读取原文片段；测试文档已清理。
- `compileall`、`ruff check backend/app --select F` 和 `git diff --check` 通过。

## 产物

- `backend/app/services/rag_embeddings.py`
- `backend/app/schemas/rag.py`
- `backend/app/api/routes/rag.py`
- `backend/app/config.py`
- `infra/mysql/001_initial_schema.sql`
- `scripts/init_database.py`

**状态：完成。**
