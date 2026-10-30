# Step 23：实现候选选址 Agent

## 已完成内容

### Agent Prompt 和 Schema

- 新增 `backend/app/agents/site_selection.py`，保存候选选址 Agent 系统 Prompt 和确定性评分规则。
- `SiteSelectionInput` 支持候选站点范围、权重、目标分数、评分规则版本、周边站点半径、数据新鲜度和最低可信度。
- `SiteSelectionOutput` 输出排序结果、分项分数、评分规则版本、权重、缺失数据和推荐动作。

### 业务数据和确定性评分

- Supervisor 按 `candidate_site_ids` 查询候选站点，随后读取区域和候选点周边站点。
- 周边站点按候选点坐标和半径重新计算距离，避免只依赖分页或查询边界。
- 评分维度包括覆盖缺口、交通、人口、竞争、建设条件、政策适配和数据可信度。
- 默认权重保存在 `DEFAULT_WEIGHTS`，通过 `scoring_rule_version` 记录版本；权重归一化由代码完成，不写入 Prompt。
- 计算候选点总分、等级、排序、附近站点数量、最近站点距离、扣分原因和推荐动作。
- 缺失关键字段、区域引用、周边站点或政策匹配时降低数据可信度，候选点最高只能得到保守等级 `C`。

### RAG、结果保存和证据

- 通过 RAG 检索选址规则、建设要求和审批条件，并执行原文 Chunk 位置校验。
- 评分结果通过 `score.result.write` 保存，携带 `run_id`、数据版本、评分规则版本、分项分数、缺失数据、扣分原因和原文证据。
- 结果仍然保持草稿状态，不自动改变候选站点生命周期，也不代表建设审批。

## 执行接口

沿用 Step 20 的 Agent 运行接口：

1. `POST /agent-runs`，`agent_type=site_selection`，`input_payload` 使用 `SiteSelectionInput`。
2. `POST /agent-runs/{run_id}/execute`，执行 Supervisor 循环。
3. `GET /agent-runs/{run_id}`，查看候选排序、雷达分项、数据缺口、工具轨迹和原文证据。

## 验证记录

- 验证权重归一化、总分、等级封顶、排序、距离和周边站点竞争分数。
- 验证缺失坐标、过期候选点、缺失建设字段和缺少周边站点时可信度下降。
- 验证 Supervisor 使用候选站点、区域、站点、RAG、证据校验、评分和评分结果写入工具。
- `compileall`、`ruff check backend/app --select F` 和 `git diff --check` 通过。

**状态：完成。**
