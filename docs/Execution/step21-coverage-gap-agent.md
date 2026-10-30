# Step 21：实现覆盖缺口 Agent

## 已完成内容

### Agent Prompt 和 Schema

- 新增 `backend/app/agents/coverage_gap.py`，保存覆盖缺口 Agent 系统 Prompt 和确定性业务规则。
- `CoverageGapInput` 支持区域、充电类型、覆盖半径、覆盖阈值、快充比例阈值、时段占用阈值、数据新鲜度和分析日期。
- `CoverageGapOutput` 输出覆盖得分、空间/快充/时段/数据不足分类、指标、最近站点距离、站点密度、时段结果和数据新鲜度。

### 业务数据和计算

- Supervisor 查询区域边界、区域站点、连接器和运营指标。
- 站点、连接器和运营指标支持分页聚合，避免只分析首个分页。
- 区域边界使用 GeoJSON Polygon/MultiPolygon，校验站点坐标是否有效且位于区域内。
- 确定性计算包括区域面积、站点密度、覆盖半径期望站点数、覆盖得分、快充连接器比例和代表点最近站点距离。
- 按小时运营指标识别高占用时段缺口；无时段指标时返回明确的数据不足分类。
- 连接器数据缺失时保留数据不足分类，并在可用的站点充电类型/数量字段上进行有限降级。

### 停止条件和证据

- 区域不存在、区域边界缺失/无效、无站点、无有效坐标时停止为 `MISSING_BUSINESS_DATA`。
- 最新站点数据超过 `stale_after_days` 时停止为 `STALE_DATA`。
- RAG 检索无命中或证据无法回溯时由 Supervisor 停止为 `EVIDENCE_INSUFFICIENT`。
- 通过 `rag.search` 和 `rag.evidence.verify` 获取并校验覆盖标准、建设规范和区域政策原文。
- 保存结果时携带数据版本、计算指标和 `AgentEvidence` 原文片段。

## 执行接口

覆盖缺口 Agent 沿用 Step 20 的运行接口：

1. `POST /agent-runs`，`agent_type=coverage_gap`，请求体中的 `input_payload` 使用 `CoverageGapInput`。
2. `POST /agent-runs/{run_id}/execute`，执行 Supervisor 循环。
3. `GET /agent-runs/{run_id}`，查看输入、阶段、工具轨迹、指标、停止原因和证据。

## 数据库兼容

- `scripts/init_database.py` 增加 `008_coverage_gap_boundary` 兼容迁移。
- 旧数据库自动补齐 `region.parent_region_id`、`region.region_type`、`region.country_code`、`region.boundary_geojson`、`region.source_file` 和 `region.deleted_at`。
- 未登记区域边界的区域会按停止条件返回，不会由 Agent 猜测边界。

## 验证记录

- 验证 GeoJSON 边界解析、点在多边形判断、距离、面积、密度、快充比例、时段缺口和过期数据停止分支。
- 验证 Supervisor 使用区域、站点、连接器、运营指标、RAG、证据校验、覆盖计算和结果写入工具。
- `compileall`、`ruff check backend/app --select F` 和 `git diff --check` 通过。

**状态：完成。**
