# 需求到实现映射

需求基线来自项目外部的 ChargeOps V3 需求文档；本矩阵把可交付要求映射到仓库中的实现和验收证据。

| 需求域 | 实现位置 | 验收证据 |
|---|---|---|
| 公开站点数据、清洗、版本和来源 | `scripts/register_afdc_public_data.py`、`data/manifests/`、`data/processed/` | Step 5/7 文档，AFDC manifest |
| 用户业务模板和失败行处理 | `data/templates/`、`backend/app/services/imports.py`、`scripts/import_data.py` | Step 6/9/28，Step 37 导入检查 |
| MySQL 业务模型和回滚 | `infra/mysql/001_initial_schema.sql`、`scripts/init_database.py`、`scripts/rollback_import.py` | Step 8/9，Step 39 MySQL 31 表恢复 |
| 认证、角色、数据范围和审计 | `backend/app/authorization.py`、`backend/app/services/auth.py`、`audit_log` | Step 11/33/36/37 |
| 站点、运营商、连接器和运营指标 | `backend/app/api/routes/catalog.py`、`operations.py` | Step 12/13，前端 Step 29 |
| RAG 上传、解析、清洗、Chunk、向量和原文 | `backend/app/services/rag_*.py`、`backend/app/api/routes/rag.py` | Step 14–17/31/35/39 |
| 五个业务 Agent | `backend/app/agents/`、`backend/app/supervisor/`、`backend/app/tools/` | Step 21–25/34/36/37 |
| 人工确认和报告导出 | `backend/app/api/routes/reports.py`、`agent_runs.py` | Step 26/37 |
| Vue 菜单、业务页面和驾驶舱 | `frontend/src/router/`、`frontend/src/views/` | Step 27–32/37 |
| 日志、监控和运行追踪 | `backend/app/logging_config.py`、`observability.py`、`monitoring` 页面 | Step 33/37/38 |
| Windows、Docker、备份和恢复 | `scripts/*_windows.ps1`、`compose.yaml`、`scripts/backup_chargeops.py`、`restore_chargeops.py` | Step 38/39 |
