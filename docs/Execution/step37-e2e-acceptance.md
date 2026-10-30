# Step 37：端到端业务验收

**状态：完成。**

## 验收范围

验收脚本 `scripts/evaluate_step37_e2e.py` 使用真实 FastAPI、MySQL、Chroma、Embedding 服务和 Vue/Vite 页面，按业务链路执行：

- 公开充电站和候选站点模板预览、清洗、导入、列表与地图查询。
- Markdown 政策上传、解析、Chunk 预览、Embedding、Chroma 入库、混合检索和原文片段展示。
- 覆盖缺口、竞争分析、候选选址、站点扩容、政策匹配五个 Agent 的创建、执行、工具轨迹、MySQL/RAG 证据和确定性计算。
- 扩容建议的 `WAITING_CONFIRMATION` 人工闸门，以及五类决策报告创建、导出和确认。
- Agent 运行、审计日志、运行监控、工具契约和 OPS_ANALYST 权限边界。
- 登录、菜单切换、页面刷新、空路由重定向和浏览器控制台错误检查。

## 执行结果

2026-10-30 使用独立 API 端口 `8010` 和前端端口 `5173` 执行：

```powershell
python scripts/evaluate_step37_e2e.py --strict
```

结果为 **133/133 checks passed，0 failed**，报告保存在 `evals/step37/reports/latest.json`。

验收过程中补充了旧数据库结构兼容处理：用户导入批次补齐 `source_url`、站点默认 `CA` 区域、负经度校验、连接器和站点状态字段兼容，以及 Chroma v2 创建 collection 时使用非空 metadata。回归验证确认真实向量入库状态为 `COMPLETED`，五个 Agent 均完成业务流程，扩容流程保留人工确认状态后再批准。

## 可复现前置条件

- MySQL 和 Chroma 已启动，Embedding 配置可用。
- 使用专用验收账号通过环境变量提供密码，不把密码写入仓库。
- 若 `/ready` 中 chat 检查暂时降级，报告会记录为显式依赖降级；MySQL、Chroma、Embedding 仍必须为 `ok`。

