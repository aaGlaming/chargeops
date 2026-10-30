# Step 24：实现站点扩容 Agent

## 已完成内容

### Agent Prompt 和 Schema

- 新增 `backend/app/agents/expansion.py`，保存站点扩容 Agent 系统 Prompt 和确定性扩容规则。
- `ExpansionInput` 支持站点范围、分析日期、运营指标窗口、峰值利用率阈值、目标利用率、连接器功率、预算单价、数据新鲜度和最低可信度。
- `ExpansionOutput` 输出站点扩容计划、指标摘要、评分规则版本、数据可信度和缺失数据。

### 业务数据和确定性扩容规划

- Supervisor 按站点范围查询站点、运营指标、故障、连接器，并支持分页聚合。
- 对每个站点计算峰值/平均利用率、故障数量、高严重度故障、现有快慢充连接器、可用功率和容量。
- 根据峰值利用率、故障集中度和可用容量确定扩容优先级。
- 生成建议新增快充/慢充连接器数量、功率调整、预算估算、前置条件、风险和推荐动作。
- 计算结果使用 `scoring_rule_version` 标记规则版本，保证同一输入可重复得到相同计划。

### 数据不足、RAG 和人工确认

- 缺少运营指标、故障记录、功率容量或连接器数据时，计划标记 `WAITING_DATA`，同时返回缺失字段和可信度。
- 通过 RAG 检索扩容规范、设备安全、配电和运维要求，并校验原文 Chunk 位置。
- 扩容方案通过 `expansion.result.write` 保存预算、容量调整、前置条件、风险和证据。
- 扩容属于高影响动作，方案生成后进入 `WAITING_CONFIRMATION`；批准后继续保存结果，拒绝则保留拒绝事件。

## 执行接口

沿用 Step 20 的 Agent 运行接口：

1. `POST /agent-runs`，`agent_type=expansion`，`input_payload` 使用 `ExpansionInput`。
2. `POST /agent-runs/{run_id}/execute`，执行 Supervisor 循环。
3. `POST /agent-runs/{run_id}/confirm`，批准或拒绝高影响扩容方案。
4. `GET /agent-runs/{run_id}`，查看扩容计划、指标、数据缺口、工具轨迹和原文证据。

## 验证记录

- 验证完整输入可以生成快慢充数量、预算、优先级和可信度。
- 验证缺少连接器/功率数据时返回 `WAITING_DATA` 和缺失数据列表。
- 验证无站点时返回 `MISSING_BUSINESS_DATA`。
- 端到端验证 Supervisor 依次执行站点、运营指标、故障、连接器、RAG、证据校验和扩容计划工具，随后等待批准；批准后执行结果写入并完成运行。
- 临时验证用户、运行、工具轨迹、事件、审计日志和扩容计划已清理。
- `compileall`、`ruff check backend/app --select F` 和 `git diff --check` 通过。

**状态：完成。**
