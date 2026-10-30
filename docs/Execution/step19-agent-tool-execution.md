# Step 19：实现 Agent 工具执行层

## 已完成内容

### 统一执行入口

- 新增 `backend/app/tools/executor.py`，所有已登记工具通过同一执行器调用。
- 新增 `POST /agent-runs/{run_id}/tools/{tool_name}`，工具名支持 `region.query`、`coverage.analyze` 等带命名空间的契约名称。
- 执行前校验工具契约、Agent 类型、运行状态、数据版本、权限、数据集和区域范围。
- 高风险扩容工具继续校验 `confirmation.expansion.publish` 权限，结果写入工具强制幂等键。

### 工具实现

- MySQL 查询：区域、运营商、站点、连接器、运营指标、故障和候选站点。
- 确定性计算：覆盖率、竞争指数、候选点评分、扩容计划和政策条件匹配。
- RAG：复用混合检索、原文片段回填和证据过滤服务，并提供 `rag.evidence.verify` 校验 Chunk、文档和原文字符位置。
- 结果写入：覆盖/竞争/政策分析摘要、候选点评分和扩容方案；扩容方案保存为 `WAITING_CONFIRMATION`。

### 轨迹、错误和幂等

- 工具执行后写入输入摘要、输出摘要、状态、错误码、重试标记和耗时，并同步 `agent_run.state_snapshot.tool_results`。
- 成功和失败分别写入 `AGENT_TOOL_EXECUTED` / `AGENT_TOOL_FAILED` 审计事件。
- 通过 `tool_call.idempotency_key` 去重；重复成功请求直接返回原工具调用和原结果，运行中的重复请求返回可重试错误。
- 将参数错误、数据库错误、向量服务错误转换为带恢复信息的机器可读错误。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/agent-runs/{run_id}/tools/{tool_name}` | 校验契约并执行 Agent 工具 |

请求示例：

```json
{
  "params": {"region_code": "CA", "page": 1, "page_size": 50},
  "idempotency_key": "optional-for-read-required-for-result-write"
}
```

## 验证记录

- 数据库初始化后表总数仍为 30，迁移版本保持 `007_agent_state_contracts`。
- 已验证区域查询、覆盖率计算、分析结果写入和重复幂等请求；重复请求返回相同 `tool_call_id` 和结果。
- 已验证工具执行结果写入运行快照和审计日志。
- `compileall`、`ruff check backend/app --select F` 和 `git diff --check` 通过。

**状态：完成。**
