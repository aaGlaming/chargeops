# Step 31：实现前端 RAG 全链路页面

## 完成内容

- 新增 `RagWorkspaceView.vue`，将文档、Chunk、Embedding、检索和原文证据放在同一个 RAG 工作台中。
- 文档列表支持文档类型、解析状态、向量状态和区域筛选，并展示版本、来源、Chunk 数量和索引状态。
- Markdown 上传支持标题、文档类型、来源 URL、区域、版本和生效日期元数据，展示上传进度、解析结果、失败原因和重试入口。
- Chunk 页面支持目标 tokens、重叠 tokens、预览、重建、历史批次、字符位置、标题路径、原文内容和校验状态。
- Embedding 页面展示模型、批次、请求数、成功数、失败数、待重试数和错误信息，并支持当前批次向量化与重建。
- 检索页面接入混合向量/关键词检索和可选确定性重排，支持 Top-K、文档类型、区域、版本和 Agent 场景筛选。
- 检索结果展示分数、文档、Chunk、版本、区域、匹配来源、字符范围、来源 URL、生效日期和原文片段。
- 调试区域展示查询改写、向量/关键词召回数量、过滤条件、重排状态和命中上下文，结果可打开原文片段抽屉。
- 新增 `frontend/src/api/rag.ts`，统一封装 RAG 文档、Chunk、Embedding 和检索 API；RAG 路由改为加载工作台页面。

## 关键文件

- `frontend/src/api/rag.ts`
- `frontend/src/views/RagWorkspaceView.vue`
- `frontend/src/router/index.ts`
- `frontend/src/styles/main.css`

## 验证

- 在 `frontend` 目录执行 `npm run build` 通过。
- 构建仅保留既有的 ECharts 大体积 chunk 警告，不影响产物生成。
