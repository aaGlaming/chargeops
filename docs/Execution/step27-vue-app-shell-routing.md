# Step 27：实现 Vue 应用壳和路由菜单

## 实现内容

- 创建 Vue 3 + TypeScript + Vite 应用入口、Vite 配置和 Element Plus 全局注册。
- 创建深色侧栏、顶栏用户区、面包屑、页面标题区、内容区和全局通知封装。
- 注册首页、站点、候选站点、覆盖缺口、竞争分析、候选选址、站点扩容、政策匹配、RAG、运行记录和审计路由。
- 使用路由 `meta` 保存页面标题、说明、图标和权限码，侧栏按登录用户角色过滤菜单。
- 增加登录页、Token/用户信息本地保存、未登录路由跳转、Token 过期清理和退出登录。
- 增加 Axios 请求封装，自动注入 Bearer Token 与 `X-Trace-ID`，统一处理 401 和错误响应中的 `trace_id`。
- 增加 ECharts 统一图表卡片，使用 `ResizeObserver` 自适应并在组件销毁时释放实例。
- 业务页先使用可复用工作区占位，统一预留加载中、空数据、失败和权限状态的承载区域，后续步骤接入真实接口。

## 目录

- `frontend/src/layouts/AppShell.vue`：应用壳编排。
- `frontend/src/components/layout/`：侧栏、顶栏和面包屑。
- `frontend/src/router/index.ts`：路由、菜单元数据和守卫。
- `frontend/src/stores/auth.ts`：前端会话状态和角色权限判断。
- `frontend/src/api/http.ts`：Axios 基础请求和错误标准化。
- `frontend/src/components/common/ChartCard.vue`：ECharts 生命周期容器。

## 验证

在 `frontend` 目录执行：

```powershell
npm run build
```

结果：`vue-tsc --noEmit` 和 `vite build` 均通过。Vite 仅提示 ECharts/Element Plus 首屏 chunk 偏大，后续页面接入时可继续按路由拆分。

