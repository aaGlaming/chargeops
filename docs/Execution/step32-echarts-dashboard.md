# Step 32：实现 ECharts 业务驾驶舱

## 完成内容

- 将首页替换为真实数据驱动的 ECharts 业务驾驶舱，支持区域筛选、近 7/30/90 日窗口和整体刷新。
- 新增站点总数、连接器总数、快充占比、高风险站点、候选站点和待确认方案六张指标卡。
- 新增充电站经纬度分布图，按运营商着色并提供图例；点击点位进入站点详情。
- 新增区域覆盖缺口热力图，按区域站点基线计算相对缺口指数，点击区域跳转区域分析。
- 新增运营商站点排行、充电类型排行、站点运营趋势和故障/恢复时间线。
- 新增候选站点评分雷达、竞争强度与候选评分散点图，并支持点击候选点打开候选站点详情。
- 新增扩容优先级列表和最近 Agent 运行列表，支持进入站点、Agent 工作台和运行记录。
- 新增 `EChartCard.vue` 通用图表容器，统一处理 ECharts 生命周期、ResizeObserver、点击事件、加载、空数据和错误状态。
- 补齐连接器、全局运营指标、全局故障、Agent 运行和报告列表的前端 API 封装；保留既有报告操作接口。
- 增强站点、区域和候选站点页面对驾驶舱 query 跳转的筛选/详情联动。

## 关键文件

- `frontend/src/views/DashboardView.vue`
- `frontend/src/components/common/EChartCard.vue`
- `frontend/src/api/catalog.ts`
- `frontend/src/api/operations.ts`
- `frontend/src/api/agents.ts`
- `frontend/src/api/reports.ts`
- `frontend/src/styles/main.css`

## 验证

- 在 `frontend` 目录执行 `npm run build` 通过。
- 执行 `python -m compileall -q backend/app` 通过。
- 执行 `git diff --check` 通过。
- 构建仅保留既有的大体积 ECharts chunk 警告，不影响产物生成。
