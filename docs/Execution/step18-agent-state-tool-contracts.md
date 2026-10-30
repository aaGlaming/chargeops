# Step 18：设计 Agent 状态和工具契约

## 已完成内容

### LangGraph 状态和五类 Agent Schema

- 新增 `AgentGraphState`，统一保存用户输入、业务范围、数据版本、Prompt/模型版本、检索查询、证据、工具结果、计算结果、结论、错误、停止原因和运行计数。
- 新增 `AgentStateSnapshot`，作为 MySQL `agent_run.state_snapshot` 的版本化快照。
- 为覆盖缺口、竞争分析、候选选址、站点扩容和政策匹配分别定义输入 Schema 和输出 Schema。
- 统一定义 `AgentEvidence`、`AgentError`、`ModelCallRecord` 和 `ConfirmationRecord`。

### 工具契约注册

- 新增工具注册表和 `/agents/contracts` 查询接口。
- 登记区域、运营商、站点、连接器、运营指标、故障、候选站点等 MySQL 查询工具。
- 登记覆盖、竞争、选址评分、扩容规划、政策匹配等确定性计算工具。
- 登记 RAG 检索工具和评分/扩容/分析结果写入工具。
- 每个契约保存输入/输出 Schema、权限码、风险等级、幂等要求、允许的 Agent、人工确认类型和可重试错误码。

### 运行和事件记录

- 新增 Agent 运行创建、列表、详情和状态转换接口。
- 状态转换校验 `PENDING → RUNNING → COMPLETED/FAILED/BLOCKED/WAITING_CONFIRMATION/CANCELLED` 等合法路径。
- `agent_run` 保存输入、业务范围、状态、停止原因、确认状态和状态快照。
- `tool_call` 保存工具权限、风险等级、幂等键、输入/输出摘要、错误、重试标记和耗时。
- 新增 `agent_run_event` 保存模型调用和人工确认事件结构。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/agents/contracts` | 查询全部工具契约，可按 Agent 类型过滤 |
| `GET` | `/agents/contracts/{tool_name}` | 查询单个工具契约 |
| `POST` | `/agent-runs` | 创建经过输入校验的 Agent 运行状态 |
| `GET` | `/agent-runs` | 查询当前用户可见的 Agent 运行 |
| `GET` | `/agent-runs/{run_id}` | 查询运行状态、工具轨迹和模型/确认事件 |
| `POST` | `/agent-runs/{run_id}/transition` | 执行合法状态转换并写入快照 |

## 权限

- 新增 `agent.run.read` 和 `agent.run.start`。
- Agent 运行查询、契约查询和运行状态更新均通过认证和角色权限校验。
- 运行详情对普通用户限制为本人创建的运行，系统管理员和审计人员可查看全部运行。

## 数据库迁移

- 新增 `agent_run_event` 表，记录模型调用和人工确认事件。
- 记录迁移版本 `007_agent_state_contracts`。

## 验证记录

- 数据库初始化后表总数为 30，迁移记录包含 `007_agent_state_contracts`。
- 五类 Agent 输入 Schema 和工具契约注册接口返回成功。
- 创建覆盖缺口 Agent 运行、转换到 `RUNNING`、写入工具调用/模型调用/确认事件并读取详情成功。
- 测试运行、工具调用和事件已清理；保留正式业务数据。
- `compileall`、`ruff check backend/app --select F` 和 `git diff --check` 通过。

## 产物

- `backend/app/agents/contracts.py`
- `backend/app/agents/registry.py`
- `backend/app/services/agent_runs.py`
- `backend/app/schemas/agents.py`
- `backend/app/api/routes/agents.py`
- `backend/app/authorization.py`
- `infra/mysql/001_initial_schema.sql`
- `scripts/init_database.py`

**状态：完成。**
