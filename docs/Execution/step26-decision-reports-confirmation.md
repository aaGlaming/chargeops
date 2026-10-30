# Step 26：实现决策报告和人工确认

## 已完成内容

### 报告模型和状态

- 新增 `agent_report` 报告表，关联 `run_id`、数据版本、数据批次、文档版本、Prompt 版本、模型版本、Embedding 模型和计算规则版本。
- 报告保存输入快照、确定性计算结果、MySQL 业务数据、RAG 原文证据和结论。
- 支持 `DRAFT`、`WAITING_CONFIRMATION`、`APPROVED`、`REJECTED` 和 `ARCHIVED` 状态。
- 新增 009 兼容迁移，初始化后工作流表包含 `agent_report`。

### 报告详情和人工确认

- 新增统一报告列表、详情、确认和归档接口。
- 扩容报告沿用扩容 Agent 的高风险确认流程；政策/补贴报告自动进入待确认；候选选址达到 A 级时进入待确认。
- 确认保存确认人、确认时间、意见、拒绝原因以及确认前后的审计状态。
- 拒绝要求填写意见，并保留原始 Agent 计算结果和证据。

### 报告导出

- 提供 Markdown 导出，包含结论、计算结果、MySQL 数据、RAG 原文证据和确认信息。
- 提供 JSON 导出，返回完整报告结构，便于前端详情页和外部归档使用。
- 报告详情包含确定性计算结果、工具读取的数据和已通过位置校验的 RAG Chunk。

## 执行接口

1. `POST /reports`，根据 `run_id` 创建决策报告。
2. `GET /reports`、`GET /reports/{report_id}`，查询报告列表和详情。
3. `POST /reports/{report_id}/confirmation`，批准或拒绝待确认报告。
4. `POST /reports/{report_id}/archive`，归档草稿、已批准或已拒绝报告。
5. `GET /reports/{report_id}/export?format=markdown|json`，导出报告。

## 验证记录

- 验证 009 数据库迁移和 `agent_report` 外键、唯一约束及状态字段。
- 真实 API 验证政策匹配运行完成后生成待确认报告。
- 验证报告详情包含 MySQL 业务数据和 3 条 RAG 证据。
- 验证 Markdown/JSON 导出、批准和归档流程。
- 验证临时运行、报告、事件、审计日志和测试用户已清理。
- `compileall`、`ruff check backend/app --select F` 和 `git diff --check` 通过。

**状态：完成。**
