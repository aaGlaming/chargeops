# Step 17：实现 RAG 检索和原文片段展示

## 已完成内容

### 查询和改写

- 新增 `POST /rag/search`，默认 `top_k=5`。
- 对查询执行控制字符清理、重复空白归一化和少量业务别名改写，并返回改写规则。
- 支持 `agent_scenario` 标签随检索请求和日志传递；Chunk metadata 中存在场景标签时会执行场景过滤。

### 混合召回和过滤

- 使用 OpenAI-compatible Embedding 生成查询向量，通过 Chroma v2 `query` 执行向量召回。
- 使用 MySQL `LIKE` 关键词召回，按词覆盖率计算关键词分数。
- 支持文档类型、区域、版本、生效日期和 Agent 场景过滤。
- 合并向量和关键词候选，按 Chunk ID 去重，使用向量/关键词加权分数排序。
- 提供可选的确定性重排：精确短语和词覆盖率会增加重排分数。

### 原文和证据状态

- 命中结果返回文档标题、版本、来源 URL、Chunk ID、字符起止位置、向量/关键词/重排分数和匹配来源。
- 从原始 Markdown 按字符位置回填 `original_fragment`，并返回 `/rag/documents/{id}/source` 跳转地址。
- 没有命中时返回 `NO_HIT`；最高分不足时返回 `EVIDENCE_INSUFFICIENT`。
- 向量服务暂时不可用时，若启用关键词召回会保留关键词结果并返回 warning。

### 检索审计

- 新增 `rag_search_log`，记录查询、改写查询、Agent 场景、过滤条件、召回数量、命中 Chunk、状态、操作者和 `run_id`。
- 同步写入审计日志 `RAG_SEARCH` 事件。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/rag/search` | 混合向量/关键词检索、过滤、排序和原文片段回填 |
| `GET` | `/rag/documents/{document_id}/source?start_char=...&end_char=...` | 打开命中的原文片段 |

请求示例：

```json
{
  "query": "充电站在线率要求",
  "top_k": 5,
  "doc_type": "business_rule",
  "region_code": "CA",
  "version": "2026-10-29",
  "effective_date_from": "2026-01-01",
  "effective_date_to": "2026-12-31",
  "agent_scenario": "coverage_gap",
  "use_vector": true,
  "use_keyword": true,
  "use_rerank": true
}
```

接口需要 `rag.read` 权限。

## 数据库迁移

- 新增 `rag_search_log`，记录每次检索的查询、过滤条件、命中和运行 ID。
- 记录迁移版本 `006_rag_search_log`。

## 验证记录

- 数据库初始化后表总数为 29，迁移记录包含 `006_rag_search_log`。
- 使用真实 Embedding 服务和 Chroma v2 完成向量召回，混合检索返回命中 Chunk 和原文片段。
- 关键词模式、文档类型、区域、版本、生效日期和 Agent 场景过滤均已验证。
- 无结果查询返回 `NO_HIT`，检索日志保存 `run_id` 和命中数量。
- `compileall`、`ruff check backend/app --select F` 和 `git diff --check` 通过。

## 产物

- `backend/app/services/rag_search.py`
- `backend/app/services/rag_embeddings.py`
- `backend/app/schemas/rag.py`
- `backend/app/api/routes/rag.py`
- `infra/mysql/001_initial_schema.sql`
- `scripts/init_database.py`

**状态：完成。**
