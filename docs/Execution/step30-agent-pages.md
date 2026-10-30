# Step 30：实现前端 5 个 Agent 页面

## 实现内容

- 为覆盖缺口、竞争分析、候选选址、站点扩容和政策匹配注册独立路由，并通过 `agentType` 复用统一工作台。
- 覆盖缺口页面提供区域、充电类型、覆盖半径、阈值和分析日期输入。
- 竞争分析页面提供坐标、半径、运营商和分析日期输入。
- 候选选址页面提供候选点多选、评分权重、目标分数和周边半径输入。
- 站点扩容页面提供站点多选、时间范围、预算和目标利用率输入。
- 政策匹配页面提供区域、申请主体、候选点、规模、连接器数量、预算和计划日期输入。
- 接入 `/agent-runs` 创建运行、Supervisor 执行、取消、重试和人工确认接口。
- 统一展示运行阶段、进度、状态、停止原因、模型事件、工具调用、错误和计数。
- 统一展示 MySQL 工具结果、RAG 原文证据和确定性计算结果。
- 运行完成或等待确认后自动创建决策报告，支持报告批准/拒绝和 Markdown/JSON 导出。
- 运行结束后发出 `chargeops:agent-completed` 事件，供驾驶舱和后续业务页面刷新。

## 主要文件

- `frontend/src/views/AgentWorkspaceView.vue`
- `frontend/src/api/agents.ts`
- `frontend/src/api/reports.ts`
- `frontend/src/router/index.ts`

## 验证

在 `frontend` 目录执行：

```powershell
npm run build
```

结果：`vue-tsc --noEmit` 和 `vite build` 均通过。Vite 仍提示 ECharts 主入口 chunk 较大，Agent 页面已按路由懒加载。

