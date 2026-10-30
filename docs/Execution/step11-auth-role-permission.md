# Step 11：实现认证、角色和权限

## 目标

为 FastAPI 建立可撤销、可审计的用户认证和授权链路，并把菜单、API、Agent 工具、数据集范围和高风险人工确认纳入同一套权限目录。

## 已完成内容

### 1. 登录和 Token

- `POST /auth/login` 接收用户名和密码，返回 Bearer access token、过期秒数和用户摘要。
- Token 使用 HMAC-SHA256 签名，包含用户 ID、Token 版本、角色、签发时间、过期时间、签发者和唯一 ID。
- `GET /auth/me` 校验签名、过期时间、签发者、用户状态和 `token_version`，支持通过提升 Token 版本撤销旧 Token。
- 密码使用 PBKDF2-SHA256 哈希，不保存明文密码。
- 支持 `AUTH_SECRET_PREVIOUS` 平滑轮换旧密钥；新 Token 始终使用 `AUTH_SECRET` 签发。
- `ACCESS_TOKEN_EXPIRE_MINUTES`、`AUTH_TOKEN_ISSUER` 和 `PASSWORD_HASH_ITERATIONS` 可由环境变量配置。

### 2. 角色和权限目录

已建立以下角色：

| 角色代码 | 角色名称 | 主要职责 |
|---|---|---|
| `OPS_ANALYST` | 运营分析师 | 站点、运营指标、覆盖缺口和竞争分析只读/分析 |
| `SITE_PLANNER` | 选址规划师 | 候选站点管理和候选点评分 |
| `OPS_LEAD` | 运维负责人 | 运营数据、故障、导入和扩容方案 |
| `POLICY_ADMIN` | 政策管理员 | 政策条件、RAG 文档和向量索引 |
| `SYSTEM_ADMIN` | 系统管理员 | 用户、角色、权限和全部业务资源 |
| `AUDITOR` | 审计人员 | 业务、运行和审计记录只读 |

权限目录目前包含 52 项，覆盖：

- 菜单权限：驾驶舱、站点、候选点、5 个 Agent、RAG、导入、审计和系统管理。
- API 权限：站点、指标、故障、候选点、政策、扩容、导入、RAG、报告、审计和用户管理。
- Agent 工具权限：站点/指标/故障查询、覆盖、竞争、评分、扩容、政策匹配、RAG 检索/重建和结果写入。
- 高风险权限：文档删除、向量重建、数据覆盖和扩容方案发布。

### 3. 数据范围和写入范围

- 新增 `user_data_scope` 表，按用户、区域和数据集记录 `can_read` / `can_write`。
- 无显式范围记录时使用角色默认范围；显式记录可以收窄到指定区域和数据集。
- 服务层 `enforce_data_scope()` 同时校验数据集类型、读写方向和区域代码。
- 默认策略限制运营分析师只读；选址规划师可写候选数据；运维负责人可写用户上传/合成运营数据；系统管理员拥有全量范围。

### 4. 三层权限校验

- 路由层：`get_current_user`、`require_permission` 和 `/auth/confirmations`。
- 服务层：`require_permission()`、`enforce_data_scope()` 和高风险确认校验。
- Agent 工具层：`backend/app/tools/authorization.py` 的 `authorize_tool()`，支持权限、数据范围、写入和人工确认组合校验。

### 5. 人工确认和审计

- `POST /auth/confirmations` 支持 `document_delete`、`vector_rebuild`、`data_overwrite` 和 `expansion_publish`。
- 所有登录成功、登录失败、Token 校验失败、权限拒绝和人工确认写入不可变 `audit_log`。
- 审计事件携带 `actor_user_id`、请求 ID、Trace ID、资源、动作、严重级别、前后状态和元数据。

## 初始化方式

授权目录使用幂等脚本初始化：

```powershell
$env:PYTHONPATH = "backend"
python scripts\init_database.py
python scripts\seed_auth.py
```

创建或重置用户时显式传入密码，不把密码写入代码或日志：

```powershell
python scripts\seed_auth.py `
  --username admin `
  --password "请替换为长度不少于 10 位的随机密码" `
  --display-name "系统管理员" `
  --role SYSTEM_ADMIN
```

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/auth/login` | 登录并签发 Token |
| `GET` | `/auth/me` | 查询当前用户、角色、权限和数据范围 |
| `POST` | `/auth/confirmations` | 提交高风险人工确认或拒绝 |

## 验证记录

- 数据库初始化后新增 `user_data_scope`，表总数为 24。
- 授权种子成功写入 6 个角色、52 个权限、181 条角色权限关联。
- 登录成功返回 200、Bearer Token 和 3600 秒过期时间。
- `/auth/me` 返回当前用户角色、52 项系统管理员权限和数据范围。
- 缺少 Token 返回 401 `AUTHENTICATION_REQUIRED`。
- 错误密码返回 401 `AUTHENTICATION_FAILED`。
- 非授权角色提交扩容发布确认返回 403 `PERMISSION_DENIED`，并生成审计事件。
- 伪造 Token 返回 401 `INVALID_TOKEN`，并生成 Token 失败审计事件。
- 系统管理员提交扩容发布确认返回 200，并生成 `MANUAL_CONFIRMATION` 审计事件。
- 服务层数据范围和 Agent 工具权限校验通过；验证账号已停用，不保留可用测试凭据。

## 产物

- `backend/app/security.py`
- `backend/app/authorization.py`
- `backend/app/services/auth.py`
- `backend/app/tools/authorization.py`
- `backend/app/api/routes/auth.py`
- `backend/app/schemas/auth.py`
- `scripts/seed_auth.py`
- `infra/mysql/001_initial_schema.sql`

