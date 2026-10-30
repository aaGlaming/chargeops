# Step 22：实现竞争分析 Agent

## 已完成内容

### Agent Prompt 和 Schema

- 新增 `backend/app/agents/competition.py`，保存竞争分析 Agent 系统 Prompt 和确定性竞争规则。
- `CompetitionInput` 支持坐标、半径、运营商筛选、距离衰减、服务阈值、数据新鲜度和分析日期。
- `CompetitionOutput` 输出周边站点、运营商分布、集中度、充电类型、连接器功率分组、服务空白、竞争风险、数据不足和新鲜度。

### 业务数据和计算

- Supervisor 按坐标和半径聚合站点分页，并按站点 ID 查询连接器数量和功率。
- 对站点重新执行 Haversine 距离校验，避免查询层边界误差进入分析结果。
- 计算距离衰减权重、运营商站点份额、距离加权份额、HHI、站点密度和竞争指数。
- 按运营商、充电类型、连接器数量和功率区间分组。
- 识别距离服务空白、无快充、连接器供给不足、功率不足和运营商服务集中。
- 输出 `HIGH_COMPETITION`、`HIGH_OPERATOR_CONCENTRATION` 和 `SERVICE_DIFFERENTIATION_REQUIRED` 风险标记。

### RAG、停止条件和保存

- 通过 RAG 检索运营商评价规则、差异化建设规则和服务要求，并校验原文 Chunk 位置。
- 没有站点、没有有效坐标、运营商筛选为空时停止为 `MISSING_BUSINESS_DATA`。
- 最新站点数据超过 `stale_after_days` 时停止为 `STALE_DATA`。
- 连接器、功率或新鲜度缺失保留可解释的数据不足分类，不补造业务数据。
- 结果通过 `analysis.result.write` 保存，携带数据版本、确定性指标和 RAG 原文证据。

## 执行接口

沿用 Step 20 的 Agent 运行接口：

1. `POST /agent-runs`，`agent_type=competition`，`input_payload` 使用 `CompetitionInput`。
2. `POST /agent-runs/{run_id}/execute`，执行 Supervisor 循环。
3. `GET /agent-runs/{run_id}`，查看站点列表、分组、指标、风险、工具轨迹和原文证据。

## 验证记录

- 验证距离、距离权重、运营商 HHI、距离加权份额、充电类型/功率分组和服务空白计算。
- 验证无站点、无有效坐标、过期数据和无连接器数据分支。
- 验证 Supervisor 使用站点、连接器、RAG、证据校验、竞争计算和分析结果写入工具。
- `compileall`、`ruff check backend/app --select F` 和 `git diff --check` 通过。

**状态：完成。**
