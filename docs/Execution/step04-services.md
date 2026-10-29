# Step 4：准备 MySQL、Chroma 和模型服务

## 已执行事项

- 检查到本机 MySQL 8.4.11 客户端和 `MySQL84` 服务。
- 使用本机已有 MySQL 实例 `127.0.0.1:3306`，创建 `chargeops` 数据库。
- 创建 `chargeops` 用户，并授予 `chargeops` 数据库范围内的权限。
- 使用 `utf8mb4` 和 `utf8mb4_0900_ai_ci` 创建数据库。
- 验证 `chargeops` 用户可以连接数据库并读取数据库名、当前用户和 MySQL 版本。
- 检查到本机已有 Chroma 1.5.9 服务监听 `127.0.0.1:8001`。
- 验证 Chroma `/api/v2/heartbeat` 返回成功。
- 使用 `.env` 中的 `CHROMA_COLLECTION=chargeops_documents` 隔离 ChargeOps 的向量集合。
- 将已有本地 OpenAI-compatible Chat、Embedding 和 Rerank 配置复用到 ChargeOps 的本地 `.env`。
- 验证 Chat、Embedding 和 Rerank 的 `/models` 接口均返回 HTTP 200。
- 创建 `scripts/check_dependencies.ps1`，统一检查 MySQL、Chroma、Chat、Embedding 和 Rerank。
- 验证依赖检查脚本执行成功并返回退出码 0。
- 确认模型 API Key 只保存在被 Git 忽略的本地 `.env`，没有写入仓库文件。

## 依赖检查结果

```text
mysql     ok     127.0.0.1:3306/chargeops
chroma    ok     127.0.0.1:8001/api/v2/heartbeat
llm       ok     models endpoint
embedding ok     models endpoint
rerank    ok     models endpoint
```

## 已知限制

- Windows `MySQL84` 服务当前为停止状态，无法通过当前权限调用 `Start-Service`。
- 当前使用已在 3306 监听的本机 MySQL 进程；Step 38 需要补充 Windows 服务启动或 Docker Compose 启动方案。
- 当前使用已存在的本机 Chroma 服务；Step 38 需要验证 Compose Chroma 卷和 ChargeOps 独立持久化目录。
- Step 10 才实现 FastAPI `/health` 和 `/ready` API；本步骤使用 `scripts/check_dependencies.ps1` 完成依赖层验证。
