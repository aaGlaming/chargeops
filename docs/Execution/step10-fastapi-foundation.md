# Step 10：搭建 FastAPI 应用基础层

## 目标

建立可运行、可观测、可扩展的 FastAPI 应用骨架，为后续业务路由、认证、Agent 和 RAG 能力提供统一入口。

## 已完成内容

### 1. 应用入口和配置

- `backend/app/main.py` 提供 `create_app()` 应用工厂，并保留 `app` 供 Uvicorn 启动。
- `backend/app/__main__.py` 支持 `python -m app` 启动。
- `backend/app/config.py` 统一读取项目 `.env` 和环境变量，覆盖 MySQL、Chroma、模型端点、认证密钥、CORS、超时和日志级别。
- 配置校验要求 `MYSQL_DSN` 存在，并在生产环境拒绝默认认证密钥。
- `/ready` 的配置摘要只返回非敏感信息，不返回 API Key、数据库密码或认证密钥。

### 2. 数据库访问基础

- `backend/app/db.py` 使用 SQLAlchemy Engine 复用连接池。
- `get_db()` 提供 FastAPI 请求级 Session 依赖。
- `transactional_session()` 为脚本或服务层提供提交、回滚和关闭的事务上下文。

### 3. 依赖就绪检查

- `backend/app/services/readiness.py` 检查 MySQL、Chroma、Chat、Embedding 和可选 Rerank 服务。
- 必需依赖全部可用时返回 `ready=true`；依赖不可用时返回 `503` 和可重试标记。
- Chroma 优先检查 `/api/v2/heartbeat`，并兼容 `/api/v1/heartbeat`。

### 4. 请求上下文、日志和错误处理

- `backend/app/middleware.py` 统一生成或透传 `X-Request-ID`、`X-Trace-ID`，并将其写入响应头。
- `backend/app/logging_config.py` 输出包含请求 ID、链路 ID、HTTP 方法、路径、状态码和耗时的结构化日志。
- `backend/app/errors.py` 统一错误响应字段：`error_code`、`message`、`trace_id`、`retryable`，并覆盖业务异常、HTTP 异常、参数校验异常和未处理异常。
- CORS 允许通过配置声明前端来源，并暴露请求追踪响应头。

### 5. 系统路由

- `GET /health`：进程存活检查，不访问外部依赖。
- `GET /ready`：依赖就绪检查，返回各服务状态和安全配置摘要。
- `/openapi.json`：由 FastAPI 自动生成接口描述。
- 当前仅接入系统基础路由，业务路由将在后续步骤接入。

## 验证记录

在项目虚拟环境中执行：

```powershell
python -m compileall -q backend\app
```

结果：通过。

本地启动 Uvicorn 后验证：

| 检查 | 结果 |
|---|---|
| `GET /health` | HTTP 200，返回 `status=ok` 和追踪 ID |
| `GET /ready` | HTTP 200，MySQL、Chroma、Chat、Embedding、Rerank 均为 `ok` |
| `GET /openapi.json` | HTTP 200，包含 `/health` 和 `/ready` |
| 未知路径 | HTTP 404，返回统一错误结构并保留请求传入的 `X-Trace-ID` |

## 启动方式

```powershell
$env:PYTHONPATH = "backend"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 产物

- `backend/app/main.py`
- `backend/app/config.py`
- `backend/app/db.py`
- `backend/app/errors.py`
- `backend/app/middleware.py`
- `backend/app/logging_config.py`
- `backend/app/services/readiness.py`
- `backend/app/api/routes/system.py`

