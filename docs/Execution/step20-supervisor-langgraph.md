# Step 20：实现 Supervisor 和 LangGraph 循环控制

## 已完成内容

### Supervisor 和 LangGraph

- 新增 `backend/app/agents/supervisor.py`，以持久化 `AgentGraphState` 为输入构建 LangGraph 循环。
- Supervisor 按用户选择路由到覆盖缺口、竞争分析、候选选址、扩容和政策匹配五类 Agent。
- 每类 Agent 依次执行业务数据读取、RAG 检索、证据校验、确定性计算、业务解释和结果保存。
- 对旧版 LangChain 环境初始化调试标志，保持 LangGraph 运行兼容。

### 限制和停止条件

- 单次运行限制模型调用次数、工具调用次数、循环次数和总耗时。
- 处理 `EVIDENCE_INSUFFICIENT`、`MISSING_BUSINESS_DATA`、`MODEL_ERROR`、`TOOL_ERROR`、`TIMEOUT` 和 `NO_PROGRESS`。
- 可重试工具错误只自动重试一次，随后保存失败状态和恢复信息。
- 候选选址和扩容查询按用户输入的候选站点/站点 ID 以及日期范围收敛结果。
- 每个阶段持续保存状态快照、工具结果、证据、结论、错误和计数。

### 确认、重试和取消

- 扩容 Agent 在生成方案并记录模型解释后进入 `WAITING_CONFIRMATION`。
- 新增确认接口，批准后恢复 `SAVE` 阶段，拒绝后以 `WAITING_CONFIRMATION` 原因失败。
- 新增重试接口，从失败/阻塞阶段的 `resume_stage` 恢复。
- 新增取消接口，统一写入 `CANCELLED` 状态和停止原因。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/agent-runs/{run_id}/execute` | 启动或继续 Supervisor/LangGraph 循环 |
| `POST` | `/agent-runs/{run_id}/confirmation` | 批准或拒绝等待确认的高影响结果 |
| `POST` | `/agent-runs/{run_id}/retry` | 重试失败或阻塞运行 |
| `POST` | `/agent-runs/{run_id}/cancel` | 取消未结束运行 |

执行参数：

```json
{
  "max_model_calls": 3,
  "max_tool_calls": 20,
  "max_loop_iterations": 8,
  "max_duration_seconds": 120
}
```

## 事件和轨迹

- `tool_call` 保存查询、RAG、计算和结果写入工具轨迹。
- `agent_run_event` 保存 `MODEL_CALL` 和 `HUMAN_CONFIRMATION` 事件。
- `agent_run.state_snapshot` 保存当前阶段、工具/模型计数、证据、结论和可恢复阶段。

## 验证记录

- 已验证五类 Agent 的 Supervisor 路径均可完成或进入预期停止状态。
- 已验证覆盖分析完成、扩容等待确认/批准后完成、失败重试和运行取消。
- 数据库初始化后表总数保持 30，验证运行、工具、事件和临时结果已清理。
- `compileall`、`ruff check backend/app --select F` 和 `git diff --check` 通过。

**状态：完成。**
