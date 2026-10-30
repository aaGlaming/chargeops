# Step 29：实现站点、区域和候选站点前端页面

## 实现内容

- 新增站点目录页面，接入区域、运营商、充电类型、状态、访问类型和来源筛选。
- 使用 ECharts 经纬度散点容器展示站点地图，支持点位点击、状态颜色、缩放自适应和组件销毁。
- 新增站点列表分页、当前页排序、来源标签和空数据/加载中/失败重试状态。
- 站点行、地图点位和路由查询参数均可打开站点详情抽屉，展示连接器、运营指标、故障、关联 Agent/扩容/评分结果和来源信息。
- 新增区域分析页面，展示区域目录、站点密度、连接器数量、运营站点比例、坐标完整率、下级区域和覆盖缺口摘要。
- 新增候选站点列表，支持区域编码和生命周期状态筛选、分页、完整度、数据新鲜度和来源标签。
- 接入候选站点创建、编辑、软删除和详情接口，详情展示坐标、预算、电力容量、交通/人口指标、周边站点、缺失字段和关联政策。
- 为页面统一处理 API 错误、`trace_id`、权限不足、加载中、空数据和失败重试状态。

## 主要文件

- `frontend/src/views/StationsView.vue`
- `frontend/src/views/RegionsView.vue`
- `frontend/src/views/CandidatesView.vue`
- `frontend/src/components/common/StationMap.vue`
- `frontend/src/api/catalog.ts`
- `frontend/src/api/operations.ts`

## 验证

在 `frontend` 目录执行：

```powershell
npm run build
```

结果：`vue-tsc --noEmit` 和 `vite build` 均通过。Vite 仅提示 ECharts 主入口 chunk 偏大，页面组件已按路由拆分。

