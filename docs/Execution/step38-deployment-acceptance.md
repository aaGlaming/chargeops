# Step 38：Windows 和 Docker 部署验收

**状态：Windows 完成；Docker 配置完成，容器运行验收受主机环境限制。**

## 新增部署资产

- `scripts/start_windows.ps1` / `scripts/stop_windows.ps1`：按 MySQL、Chroma、FastAPI、Vue 顺序检查、启动和停止本机服务。
- `scripts/init_database.ps1`：执行数据库迁移和权限目录种子。
- `scripts/import_sample_data.ps1`：导入公开或合成示例数据。
- `scripts/index_rag_documents.ps1`：幂等注册 AFDC Markdown 资料并建立 Chroma 索引。
- `backend/Dockerfile`、`frontend/Dockerfile`、`frontend/nginx.conf`：后端运行镜像、前端构建镜像和 SPA 回退配置。
- `compose.yaml`：MySQL、Chroma、FastAPI、Vue 四服务、健康检查、依赖顺序、重启策略和 MySQL/Chroma/RAG/日志卷。

后端日志新增 `LOG_FILE` 支持；Compose 将 JSON 日志写入 `logs-data` 卷，上传文件写入 `rag-data` 卷，业务导入批次和 Agent 审计记录保存在 MySQL 卷。

## Windows 验收

执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_windows.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/init_database.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/import_sample_data.ps1 -Dataset synthetic
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/index_rag_documents.ps1
python scripts/evaluate_step38_deployment.py --strict
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stop_windows.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_windows.ps1
```

实际验证结果：数据库迁移 31 张表、权限目录 6 个角色、合成数据 559 行全部导入成功，AFDC 两份公开 Markdown 文档保持 `INDEXED`。部署验收脚本共 41 项检查全部通过，覆盖 `/health`、`/ready`、Swagger、前端根页面、健康页面、仪表盘和 5 个 Agent 路由。

## Docker 验收结果

静态检查确认 Compose 包含四个服务、四个持久化卷、健康检查、服务健康依赖和 `unless-stopped` 重启策略；前后端 Dockerfile 和 Nginx SPA 配置均存在且可构建所需文件完整。

当前 Windows 主机未安装 Docker CLI 或 Docker Desktop，因此无法执行 `docker compose up -d --build`、容器重启和实际卷恢复。本次报告将这两项标记为显式 skipped，状态为 `PASS_WITH_LIMITATION`，不会把未执行的容器运行结果伪装成通过。安装 Docker Desktop 后可直接运行：

```powershell
docker compose up -d --build
docker compose ps
python scripts/evaluate_step38_deployment.py --strict
docker compose restart mysql chroma backend frontend
docker compose down
```

验收报告：`evals/step38/reports/latest.json`。
