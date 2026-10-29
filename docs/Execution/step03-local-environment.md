# Step 3：配置 Windows 本地开发环境

## 已执行事项

- 已确认 Windows 可用的 Python、Node.js、npm 和 Git。
- 使用 Python 3.11.16 创建项目专属虚拟环境：`.venv`。
- 已创建并固定后端依赖文件：`backend/requirements.txt`。
- 已创建后端工具配置：`backend/pyproject.toml`。
- 已在项目 `.venv` 安装 FastAPI、Uvicorn、Pydantic、SQLAlchemy、PyMySQL、LangChain、LangGraph、Chroma、Markdown 解析、pytest、Ruff 和 mypy。
- 项目专属 `.venv` 执行 `pip check`，结果为 `No broken requirements found.`。
- 已确认项目专属 `.venv` 可以导入 FastAPI、SQLAlchemy、LangChain、LangGraph、Chroma、Markdown 解析器、Ruff 和 mypy。
- 已创建前端 `package.json`、`package-lock.json`、`tsconfig.json` 和 `env.d.ts`。
- 已安装 Vue、TypeScript、Vite、Vue Router、Element Plus、ECharts、Axios、Pinia 和 Vue 类型检查依赖。
- 已确认 `vite --version` 和 `vue-tsc --version` 可执行。
- 已从 `.env.example` 生成本地 `.env`，生成随机 `AUTH_SECRET`，模型 API Key 保持为空。
- 已确认 `.env` 被 `.gitignore` 忽略。
- 为避免影响其他项目，已恢复共享环境中临时升级的 Ruff、Markdown 解析器和 mypy 版本。

## 环境版本

| 工具 | 版本 |
|---|---|
| Python 项目环境 | 3.11.16 |
| Node.js | 24.19.0 |
| npm | 11.17.0 |
| Git | 2.47.1.windows.2 |
| Vite | 8.3.4 |
| TypeScript | 6.0.3 |
| Vue TSC | 3.3.13 |

## 已知限制

- 当前 Windows 环境未安装 Docker Desktop，`docker --version` 和 `docker compose version` 不可用。
- Docker 安装和 Compose 服务启动留到 Step 4 或 Step 38 执行。
- 当前没有创建业务代码，因此没有执行 FastAPI 启动、Vue 构建或业务测试。
