# ChargeOps 交付说明

## 交付范围

ChargeOps 是面向充电网络运营商、园区和商业地产团队的站点选址与扩容决策平台。系统把公开站点、用户上传模板、运营指标、候选站点和政策 Markdown 统一到 MySQL 与 Chroma，通过五个可追溯 Agent 输出业务结论、确定性计算、MySQL 证据和 RAG 原文片段。

系统架构见 [`chargeops-system.mmd`](../architecture/chargeops-system.mmd)，需求映射见 [`requirements-implementation-matrix.md`](requirements-implementation-matrix.md)。

## 快速启动

### Windows 本地

1. 准备 Python 3.11、Node.js 22、MySQL 8.4、Chroma 和 `.env`。
2. 复制 `.env.example` 为 `.env`，配置数据库、认证密钥和可选模型服务。
3. 执行初始化、示例数据和 RAG 索引：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/init_database.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/import_sample_data.ps1 -Dataset all
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/index_rag_documents.ps1
```

4. 启动服务：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_windows.ps1
```

默认地址：API `http://127.0.0.1:8000`、Swagger `/docs`、前端 `http://127.0.0.1:5173`。端口被其他项目占用时，使用 `-ApiPort` 和 `-FrontendPort`；脚本会校验占用端口是否确实是 ChargeOps API。

### Docker Compose

先配置生产级 `AUTH_SECRET`、MySQL 密码和模型环境变量，再执行：

```powershell
docker compose up -d --build
docker compose ps
```

Compose 启动 MySQL、Chroma、FastAPI 和 Nginx/Vue，使用 `mysql-data`、`chroma-data`、`rag-data`、`logs-data` 四个卷。停止服务：

```powershell
docker compose down
```

## 数据、RAG 和评测版本

| 内容 | 版本/结果 |
|---|---|
| 公开数据 | AFDC 加州公开电站快照，版本 `2026-10-29`，原始 20,369 行，SHA-256 见 manifest |
| 清洗结果 | 20,355 行通过，14 行进入失败文件；保留来源、批次和数据版本 |
| 合成数据 | `synthetic_demo_2026-10-29`，12 个演示站点和业务样例 |
| RAG 原文 | `rag_docs/`，政策、站点字段字典和公开数据说明 |
| Chunk | 清洗版本 `clean-v1`，批次参数、字符位置和原文片段写入 MySQL |
| Embedding | 当前运行配置来自 `.env`；公开快照索引记录 `BAAI/bge-m3` |
| 向量库 | Chroma collection `chargeops_documents`，Chunk ID 与 `rag_chunk.chroma_id` 关联 |

## 五个 Agent

| Agent | 主要输入 | 工具/计算 | 输出与风险 |
|---|---|---|---|
| 覆盖缺口 | 区域、半径、快充比例、时间窗口 | 区域/站点/连接器/运营指标查询，`coverage.analyze` | 覆盖率、缺口类型、时效；保存分析结果 |
| 竞争分析 | 坐标、半径、服务阈值 | 站点/连接器/运营商查询，`competition.analyze` | 周边站点、集中度、竞争指数和服务缺口 |
| 候选选址 | 候选点、半径、评分权重 | 区域/站点/候选点查询，`site.score` | 分项评分、雷达数据、推荐等级 |
| 站点扩容 | 站点、运营指标、故障窗口 | 站点/连接器/指标/故障查询，`expansion.plan` | 连接器数量、预算和优先级；必须人工确认 |
| 政策匹配 | 区域、主体、规模、材料 | 区域/候选点/政策查询，`policy.match` | 政策版本、资格、缺失材料和截止日期 |

所有 Agent 都经过 Supervisor 循环控制、工具权限校验、RAG 证据回溯、幂等结果写入和停止原因记录。

## API、页面和权限

API 分组：认证 `/auth/*`；健康 `/health`、`/ready`；主数据 `/regions`、`/operators`、`/stations`、`/connectors`；运营 `/metrics`、`/faults`、`/candidate-sites`；导入 `/imports/*`；RAG `/rag/*`；Agent `/agents/*`、`/agent-runs/*`；报告 `/reports/*`；审计监控 `/audit-logs`、`/monitoring/*`。完整请求和响应以 `/docs` OpenAPI 为准。

前端路由：`/dashboard`、`/imports`、`/regions`、`/stations`、`/candidates`、`/agents/coverage`、`/agents/competition`、`/agents/site-selection`、`/agents/expansion`、`/agents/policy`、`/rag`、`/runs`、`/audit`、`/monitoring`。

角色包括运营分析师、选址规划师、运维负责人、政策管理员、系统管理员和审计人员。菜单权限、数据范围、Agent 工具权限和高风险确认权限分别记录；扩容发布和向量重建等操作保留人工确认与审计事件。

## 评测与验收

| 阶段 | 结果 |
|---|---|
| 确定性基线 | 15/15 通过 |
| RAG 评测 | 10/10 查询通过；Recall@K、Hit Rate@K、MRR、来源正确率、片段可定位率均为 1.0 |
| Agent 安全验证 | 65/65 通过 |
| 端到端业务验收 | 133/133 通过 |
| Windows/Docker 部署验收 | 41/41 可执行检查通过；Docker 运行项因主机未安装 Docker CLI 标记 skipped |
| 备份恢复 | SHA-256 59/59；MySQL 31 表；Chroma collection 1；RAG 命中 3；Agent `COMPLETED` |

报告目录：`evals/step34` 至 `evals/step39`。

## 日志、监控、备份和恢复

- API 输出结构化 JSON 日志，设置 `LOG_FILE` 后同时写入文件；Compose 使用 `logs-data` 卷。
- `/monitoring/overview` 汇总 MySQL、Chroma、模型、磁盘、错误率和 P95；`/audit-logs` 查询不可变操作记录。
- `scripts/backup_chargeops.py` 生成 MySQL dump、Chroma 文件、原文和评测归档及 SHA-256 清单。
- `scripts/restore_chargeops.py` 在独立目录恢复文件，在 MySQL 影子表验证 dump，启动临时 Chroma 验证 collection，并可重新执行 RAG 和 Agent。

## 已知限制与交接事项

- 当前验收主机没有 Docker CLI/Desktop；Compose 文件、Dockerfile、健康检查和卷定义已完成，但容器实际启动/重启/卷恢复需在安装 Docker Desktop 的主机执行。
- 外部 Chat、Embedding、Rerank 服务依赖网络和密钥；模型不可用时健康检查会显式降级，数据管理和 RAG 管理页面仍可打开。
- 不要提交 `.env`、API Key、生产密码、备份目录、恢复目录或真实用户上传文件；生产部署必须替换示例认证密钥和默认密码。
- AFDC 数据是带下载时间和版本的公开快照，重新下载后应生成新的 raw hash、cleaning manifest、导入批次和 RAG 版本。

## 交付清单

- [执行状态](../Execution/step-status.md)
- [数据字典](../data-dictionary.md)
- [架构图](../architecture/chargeops-system.mmd)
- [需求实现矩阵](requirements-implementation-matrix.md)
- [部署验收](../Execution/step38-deployment-acceptance.md)
- [备份恢复验收](../Execution/step39-backup-restore.md)

## Git 交付标识

Step 40 完成后创建并推送 annotated tag：`v0.1.0-step40`。复现交付内容：

```powershell
git clone https://github.com/aaGlaming/chargeops.git
Set-Location chargeops
git checkout v0.1.0-step40
Copy-Item .env.example .env
```
