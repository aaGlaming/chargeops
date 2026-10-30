# ChargeOps 充电站选址与扩容决策平台

ChargeOps 面向充电网络运营商、园区和商业地产团队，提供公开站点数据、运营业务数据、政策知识库和五个业务 Agent 的可追溯决策支持。系统由 FastAPI、MySQL、Chroma 和 Vue 组成，支持站点覆盖分析、竞争分析、候选选址、站点扩容和政策匹配。

## 交付状态

Step 5–40 已完成。Step 40 的完整交付说明、启动命令、数据版本、评测结果、限制和交接事项见 [`docs/delivery/chargeops-delivery.md`](docs/delivery/chargeops-delivery.md)。需求与代码实现映射见 [`docs/delivery/requirements-implementation-matrix.md`](docs/delivery/requirements-implementation-matrix.md)。

## 快速启动

### Windows 本地

```powershell
Copy-Item .env.example .env
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/init_database.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/import_sample_data.ps1 -Dataset all
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/index_rag_documents.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_windows.ps1
```

默认地址：API `http://127.0.0.1:8000`，Swagger `http://127.0.0.1:8000/docs`，前端 `http://127.0.0.1:5173`。运行参数和端口冲突处理见 [`scripts/start_windows.ps1`](scripts/start_windows.ps1)。

### Docker Compose

```powershell
Copy-Item .env.example .env
# 先在 .env 中替换生产密钥和密码
docker compose up -d --build
docker compose ps
```

Docker 运行要求、健康检查和未完成的主机前置条件见 [`docs/Execution/step38-deployment-acceptance.md`](docs/Execution/step38-deployment-acceptance.md)。

## 仓库结构

| 目录 | 内容 |
|---|---|
| `backend/` | FastAPI 路由、服务、权限、RAG、Agent 和监控 |
| `frontend/` | Vue 3、Pinia、Vue Router、ECharts 页面 |
| `infra/` | MySQL schema、迁移、Compose 和 Nginx |
| `data/` | 原始/清洗公开数据、模板、合成数据和 manifest |
| `rag_docs/` | 可追溯的 Markdown 政策和业务知识 |
| `scripts/` | 初始化、导入、索引、评测、部署、备份和恢复脚本 |
| `docs/` | 执行状态、架构、数据字典、部署和交付文档 |
| `evals/` | Step 34–39 的数据集、报告和验收证据 |

## 五个业务 Agent

- 覆盖缺口：计算区域覆盖率、缺口类型和时间窗口。
- 竞争分析：分析周边站点、运营商集中度和服务缺口。
- 候选选址：按需求、竞争、容量、距离和政策条件输出候选评分。
- 站点扩容：结合利用率、故障和连接器类型提出扩容计划，需人工确认。
- 政策匹配：按区域、主体和项目规模匹配政策、资格和材料缺口。

每次运行都会保留状态、工具调用、MySQL 证据、RAG 原文片段、停止原因和审计记录。

## 评测结果

- 确定性基线：15/15 通过。
- RAG：10/10 查询通过，Recall@K、Hit Rate@K、MRR、来源正确率和片段可定位率均为 1.0。
- Agent 安全验证：65/65 通过。
- 端到端业务验收：133/133 通过。
- Windows/Docker 部署检查：41/41 可执行检查通过；主机未安装 Docker CLI，容器运行项标记为 skipped。
- 备份恢复：SHA-256 59/59，MySQL 31 表，Chroma collection 1，RAG 命中 3，Agent 状态 `COMPLETED`。

## 重要文档

- [完整交付说明](docs/delivery/chargeops-delivery.md)
- [需求实现矩阵](docs/delivery/requirements-implementation-matrix.md)
- [执行状态](docs/Execution/step-status.md)
- [系统架构图](docs/architecture/chargeops-system.mmd)
- [MySQL 数据字典](docs/data-dictionary.md)
- [执行手册](docs/chargeops.md)
- [部署验收](docs/Execution/step38-deployment-acceptance.md)
- [备份恢复验收](docs/Execution/step39-backup-restore.md)

## 安全和数据约束

不要提交 `.env`、API Key、生产密码、备份/恢复目录、日志运行产物或真实用户上传文件。重新下载公开数据时，应保留下载日期、原始 hash、清洗 manifest、导入批次和 RAG 版本，以便复现和回滚。

最终交付标签：`v0.1.0-step40`。
