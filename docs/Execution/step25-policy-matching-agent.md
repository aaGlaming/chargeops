# Step 25：实现政策与补贴匹配 Agent

## 已完成内容

### Agent Prompt 和 Schema

- 新增 `backend/app/agents/policy_matching.py`，保存政策与补贴匹配 Agent 系统 Prompt 和确定性匹配规则。
- `PolicyMatchingInput` 支持区域、申请主体、候选站点、站点类型、政策类型、建设规模、快慢充数量、项目预算、计划日期和已有材料。
- `PolicyMatchingOutput` 输出逐条政策结果、条件矩阵、通过/部分通过/不通过/无法判断分类、材料缺口、政策版本、截止日期、可信度和规则版本。

### MySQL 条件匹配

- Supervisor 按区域和候选站点范围读取候选点字段及政策条件。
- `policy.query` 支持区域、申请主体、政策类型、生效日期和数据版本筛选，并保留过期政策用于明确失败原因。
- 支持 `EQ`、`EQUALS`、`IN`、`NOT_IN`、`GTE`、`LTE`、`GT`、`LT` 和 `CONTAINS` 条件。
- 支持 JSON 条件值、候选站点专属 `eligibility:<external_id>` 条件、有效期、申请截止日期和材料清单。
- 缺少实际字段时标记 `UNKNOWN`，部分条件通过但材料不足或字段缺失时标记 `PARTIAL`。

### RAG、结果保存和证据

- 复用政策资格、申请材料、补贴金额、截止日期和限制条件 RAG 查询。
- 执行原文 Chunk 位置校验，运行状态保存政策版本、条件结果、材料清单和原文证据。
- 通过 `analysis.result.write` 按 `run_id` 保存匹配结果和规则版本；结果仅作为申请准备草案，不代表政策审批或补贴承诺。

## 执行接口

沿用 Step 20 的 Agent 运行接口：

1. `POST /agent-runs`，`agent_type=policy_matching`，`input_payload` 使用 `PolicyMatchingInput`。
2. `POST /agent-runs/{run_id}/execute`，执行 Supervisor 循环。
3. `GET /agent-runs/{run_id}`，查看政策条件矩阵、材料清单、截止日期、工具轨迹和原文证据。

## 验证记录

- 验证政策条件通过、部分通过、失败和无法判断四种状态。
- 验证 JSON 条件、候选站点专属条件、材料缺口和截止日期判断。
- 验证 MySQL 政策查询按区域/主体/生效日期筛选，候选站点查询按候选点范围收敛。
- 验证政策匹配确定性计算和 `analysis.result.write` 结果保存契约。
- `compileall`、`ruff check backend/app --select F` 和 `git diff --check` 通过。

**状态：完成。**
