# Step 33：完善日志、审计和运行监控

**状态：完成。**

## 已完成内容

- 请求中间件统一生成并传播 `request_id`、`trace_id`，认证成功后绑定 `user_id`；Agent 运行、工具调用和导入批次通过审计资源自动关联 `agent_run_id`、`tool_call_id` 和 `import_batch_id`。
- 新增进程内遥测采样，记录 HTTP、数据库、模型、Embedding、RAG、Chroma、工具和确定性计算耗时，并计算调用数、错误数、错误率和 P95 延迟。
- 结构化日志、审计前后状态和 Agent 输入/输出摘要统一递归脱敏，屏蔽 API Key、Authorization、Token、密码、Cookie、上传原始行和模型响应等字段，并限制字符串和数组长度。
- 新增 `/audit-logs` 审计查询接口，支持动作、资源类型、严重级别、Trace、Agent Run 和 Import Batch 过滤及分页。
- 新增 `/monitoring/overview`、`/monitoring/alerts` 和告警开关接口，展示 MySQL、Chroma、Chat/Embedding 模型、磁盘、HTTP 错误率、P95 和业务批次统计；关闭/恢复告警会追加 `ALERT_DISABLED`/`ALERT_ENABLED` 审计事件。
- Agent 运行列表/详情页展示停止原因、工具轨迹、模型事件、耗时和状态快照；导入批次详情页会加载失败行并支持失败报告下载和回滚记录查看。
- 前端新增运行记录、审计日志和运行监控页面，系统管理员可切换告警，审计人员可读取运行、监控和审计信息。

## 主要文件

- `backend/app/telemetry.py`
- `backend/app/services/observability.py`
- `backend/app/api/routes/observability.py`
- `backend/app/schemas/observability.py`
- `frontend/src/views/RunsView.vue`
- `frontend/src/views/AuditView.vue`
- `frontend/src/views/MonitoringView.vue`

## 验证

- `python -m compileall -q backend/app`
- `npm run build`（`frontend/`）
- `git diff --check`
