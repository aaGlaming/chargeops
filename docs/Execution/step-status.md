# chargeops 执行状态

## Step 1：确认项目范围和验收边界

**状态：完成。**

- 范围、角色、5 个业务 Agent、RAG 菜单、MySQL 数据边界和前端验收边界已记录在 `step01-scope.md`。
- 公开数据、用户上传数据和合成数据的 `source_type` 已固定。
- MVP 验收标准和非目标已固定。
- Step 2 已执行。

## Step 2：创建 Git 仓库和项目目录

**状态：完成。**

- Git 仓库已在项目目录初始化，当前分支为 `main`。
- 已添加远程仓库 `https://github.com/aaGlaming/chargeops.git`。
- 已创建项目骨架、`.gitignore`、`.env.example`、`compose.yaml` 和 `VERSION`。
- 已创建 Step 2 执行记录：`step02-repository.md`。
- 初始提交 `f6f43b8` 已推送到远程 `main` 分支。
- Step 3 已执行。

## Step 3：配置 Windows 本地开发环境

**状态：完成，Docker Desktop 待补充。**

- 已创建项目专属 `.venv` 并安装后端依赖，`pip check` 通过。
- 已安装前端依赖并生成 `frontend/package-lock.json`。
- 已生成本地 `.env`，模型密钥为空且文件已被 Git 忽略。
- Docker Desktop 未安装，容器依赖启动留待 Step 4 或 Step 38。
- 已创建 Step 3 执行记录：`step03-local-environment.md`。
- Step 4 已执行。

## Step 4：准备 MySQL、Chroma 和模型服务

**状态：完成，Windows 服务启动方式待后续完善。**

- `chargeops` MySQL 数据库和本地业务用户已创建，连接验证通过。
- 本机 Chroma `127.0.0.1:8001` 心跳验证通过。
- Chat、Embedding 和 Rerank 模型端点验证通过。
- 已创建依赖检查脚本：`scripts/check_dependencies.ps1`。
- 已创建 Step 4 执行记录：`step04-services.md`。
- MySQL Windows 服务当前不能由本次会话启动，后续在 Step 38 处理持久化启动方式。
- Step 5 已执行。

## Step 5：下载并登记公开充电站数据

**状态：完成。**

- 已从 AFDC 官方接口下载加州公开、已开放的电动汽车充电站快照。
- 已保存原始 CSV、规范化 CSV、SHA-256 来源清单和字段说明。
- 已在 MySQL 登记导入批次、区域、运营商、20,369 个站点和 20,677 条连接器分类记录。
- 已生成两份 Markdown 来源文档，登记到 MySQL `rag_document` / `rag_chunk` 并写入 Chroma `chargeops_documents`。
- 已创建可重复执行脚本：`scripts/register_afdc_public_data.py`。
- 详细记录见 `step05-public-data.md`。
- Step 6 已执行。

## Step 6：准备用户上传模板和合成业务数据

**状态：完成。**

- 已创建候选站点、运营指标、故障、扩容案例和政策匹配模板。
- 已使用固定随机种子生成演示业务数据，并写入 `data/raw/synthetic`。
- 已覆盖正常、高利用率、低利用率、故障集中、缺失坐标、缺失容量和过期数据场景。
- 每条合成记录包含 `source_type`、生成器版本、生成时间和合成批次 ID。
- 已生成合成数据清单和 SHA-256 校验清单。
- 详细记录见 `step06-synthetic-data.md`。
- Step 7 已执行。

## Step 7：建立公开数据清洗和统一映射

**状态：完成。**

- 已从原始 AFDC CSV 生成统一字段的清洗结果，未修改原始文件。
- 已完成站点、运营商、地址、状态、访问类型、连接器数量、日期和时区映射。
- 已验证坐标范围，识别重复站点指纹和连接器复合键。
- 已输出清洗结果、失败行、字段映射、字段质量统计和清洗批次清单。
- 20,355 条记录通过清洗，14 条重复站点指纹记录进入失败行文件。
- 详细记录见 `step07-public-data-cleaning.md`。
- Step 8 已执行。

## Step 8：设计 MySQL 数据模型

**状态：完成，Step 9 负责迁移和初始化。**

- 已完成认证权限、业务主数据、运营数据、候选站点、政策、评分、扩容、Agent、RAG 和审计模型设计。
- 已输出目标 DDL：`infra/mysql/001_initial_schema.sql`。
- 已输出 ER 图：`docs/architecture/chargeops-mysql-erd.mmd`。
- 已输出数据字典：`docs/data-dictionary.md`。
- 已定义来源、版本、批次、外键、唯一约束、索引、软删除和不可变审计规则。
- 当前 Step 5 临时表未被删除，Step 9 已通过兼容迁移补齐导入所需字段。
- Step 9 已执行。

## Step 9：实现数据库初始化、导入和回滚

**状态：完成。**

- 已执行数据库初始化和兼容迁移，记录模型迁移版本。
- 已实现公开清洗数据和合成数据导入、批次统计、失败行记录和幂等更新。
- 已实现整批回滚脚本，并完成合成批次回滚后重新导入验证。
- 已创建 `schema_migration` 和 `import_row_error` 工作流表。
- 详细记录见 `step09-database-init-import-rollback.md`。
- Step 10 已执行。

## Step 10：搭建 FastAPI 应用基础层

**状态：完成。**

- 已建立 FastAPI 应用工厂、配置加载、SQLAlchemy Session 依赖和事务上下文。
- 已建立 MySQL、Chroma、Chat、Embedding、Rerank 就绪检查。
- 已建立请求/链路 ID、中间件、结构化日志和统一错误响应。
- 已接入 `/health`、`/ready` 和自动 OpenAPI 描述入口。
- 已验证基础服务启动、依赖就绪、OpenAPI 和 404 错误响应。
- 详细记录见 `step10-fastapi-foundation.md`。
- Step 11 已执行。

## Step 11：实现认证、角色和权限

**状态：完成。**

- 已实现 PBKDF2 密码哈希、HMAC Bearer Token、Token 过期、版本撤销和密钥轮换配置。
- 已建立运营分析师、选址规划师、运维负责人、政策管理员、系统管理员和审计人员六类角色。
- 已建立菜单、API、Agent 工具和高风险确认权限，并通过路由、服务层和工具层执行校验。
- 已增加用户数据集/区域读写范围表和默认角色范围策略。
- 已实现登录、当前用户、人工确认接口，以及登录、Token 失败、权限拒绝和确认审计。
- 已创建幂等授权初始化脚本：`scripts/seed_auth.py`。
- 详细记录见 `step11-auth-role-permission.md`。
- Step 12 已执行。

## Step 12：实现区域、运营商、站点和连接器模块

**状态：完成。**

- 已实现区域列表、层级详情、区域筛选和边界字段返回。
- 已实现运营商列表、详情和关联站点预览。
- 已实现充电站分页、状态/访问类型/充电类型/来源/版本筛选和详情接口。
- 已实现连接器类型、数量、功率、状态和来源查询接口。
- 已实现中心点半径、经纬度边界框和地图点位接口。
- 已在目录列表和详情中统一返回公开、用户上传、合成和 Agent 来源标签。
- 已加入站点运营指标、故障、Agent 运行和扩容方案关联入口。
- 详细记录见 `step12-catalog-modules.md`。
- Step 13 已执行。

## Step 13：实现运营指标、故障和候选站点模块

**状态：完成。**

- 已实现站点日/小时运营指标查询，支持日期、小时、来源和版本筛选。
- 已实现故障事件查询、创建、严重等级、恢复时间和状态更新。
- 已实现候选站点创建、编辑、详情、软删除和生命周期状态管理。
- 已实现候选站点与周边站点、区域政策的关联查询。
- 已实现候选站点关键字段完整度、数据新鲜度和可推荐性计算。
- 缺少关键字段或数据过期时禁止进入 `RECOMMENDED` 状态。
- 详细记录见 `step13-operations-faults-candidates.md`。
- Step 14 已执行。

## Step 14：实现 RAG 文档上传和 Markdown 解析

**状态：完成。**

- 已实现 Markdown 文件上传、扩展名/内容类型/UTF-8/大小/文件名校验和安全存储。
- 已实现 SHA-256 去重、文档元数据登记、版本冲突检测和原始文件保留。
- 已实现标题、段落、列表、表格、编号条款和代码围栏解析。
- 已新增 `rag_document_section` 保存解析区块、标题路径、字符位置和元数据。
- 已实现解析状态、失败原因和原文件重试接口。
- 已将上传、重复、解析成功、解析失败和重试写入审计日志。
- 详细记录见 `step14-rag-upload-markdown.md`。
- Step 15 已执行。

## Step 15：实现文本清洗和 Chunk 预览

**状态：完成。**

- 已实现 Markdown 文本清洗、重复页眉页脚处理和结构化 Chunk 生成。
- 默认 Chunk 参数为 800 tokens / 120 tokens，可通过接口调整。
- 已新增 Chunk 批次表，预览和重建均保留历史批次，不覆盖旧 Chunk。
- 已保存 Chunk ID、标题路径、序号、文档版本、字符位置、清洗版本和校验结果。
- 已实现 Chunk 预览、历史批次查询、空/超长/标题/条款编号校验和原文位置跳转地址。
- 详细记录见 `step15-rag-cleaning-chunk-preview.md`。

## Step 16：实现 Embedding 和 Chroma 入库

**状态：完成。**

- 已实现 OpenAI-compatible Embedding 客户端，支持批量、超时、指数退避重试和限流。
- 已实现 Chroma v2 HTTP 入库，保存 Chunk ID、文档 ID、区域、类型、版本、字符位置和模型元数据。
- 已实现单文档向量化、指定 Chunk 批次向量化、文档级删除重建和失败批次重试。
- 已新增 `rag_embedding_batch` / `rag_embedding_item`，记录模型、参数、成功数、失败数、待重试数和错误详情。
- 已实现幂等请求、失败保留、文档 `vector_status` 更新和按版本删除向量。
- 详细记录见 `step16-embedding-chroma-index.md`。

## Step 17：实现 RAG 检索和原文片段展示

**状态：完成。**

- 已实现查询清洗、确定性查询改写、向量召回和 MySQL 关键词召回。
- 已实现文档类型、区域、版本、生效日期和 Agent 场景过滤。
- 已实现候选合并、Chunk 去重、加权排序和可选确定性重排。
- 已实现命中 Chunk 的文档信息、分数、原文片段和字符位置跳转地址。
- 已实现 `NO_HIT`、`EVIDENCE_INSUFFICIENT` 状态和向量服务降级 warning。
- 已新增 `rag_search_log`，记录查询、过滤条件、命中结果和 `run_id`。
- 详细记录见 `step17-rag-search-original-fragment.md`。

## Step 18：设计 Agent 状态和工具契约

**状态：完成。**

- 已定义五类 Agent 的输入、输出、错误、证据和 LangGraph 状态 Schema。
- 已登记 MySQL 查询、确定性计算、RAG 检索和结果写入工具契约。
- 每个工具保存权限码、风险等级、幂等要求、允许的 Agent、确认类型和可重试错误码。
- 已实现 Agent 运行创建、状态转换、状态快照、工具调用、模型调用和人工确认事件记录。
- 已新增 `agent_run_event` 表和 `agent.run.read` / `agent.run.start` 权限。
- 详细记录见 `step18-agent-state-tool-contracts.md`。

## Step 19：实现 Agent 工具执行层

**状态：完成。**

- 已实现统一 Agent 工具执行入口，覆盖 MySQL 查询、确定性计算、RAG 检索和结果写入。
- 执行前校验契约、Agent 类型、运行状态、权限、数据范围、数据版本、风险等级和幂等要求。
- 执行后记录输入/输出摘要、耗时、错误、重试标记、运行快照和审计事件。
- 结果写入支持评分、扩容方案和分析摘要；重复写入按幂等键返回原结果。
- 详细记录见 `step19-agent-tool-execution.md`。

## Step 20：实现 Supervisor 和 LangGraph 循环控制

**状态：完成。**

- 已实现五类 Agent 的 Supervisor 路由和 LangGraph 循环控制。
- 每类 Agent 按业务数据、RAG、计算、解释和保存阶段执行，并持续保存状态快照。
- 已实现模型/工具/证据不足/数据不足/超时/无进展停止条件和单次运行限制。
- 已实现高影响扩容结果的等待确认、批准恢复、拒绝、失败重试和运行取消。
- 已新增 Supervisor 执行、确认、重试和取消接口。
- 详细记录见 `step20-supervisor-langgraph.md`。

## Step 21：实现覆盖缺口 Agent

**状态：完成。**

- 已新增覆盖缺口 Agent 系统 Prompt、输入扩展和输出指标结构。
- 已接入区域边界、站点、连接器和运营指标查询，并支持分页聚合。
- 已实现空间覆盖、站点密度、快充比例、最近站点距离和时段缺口确定性计算。
- 已实现区域边界缺失、无效坐标、站点为空、数据过期和数据不足停止条件。
- 已接入覆盖标准/建设规范/区域政策 RAG 检索、证据校验和结果保存。
- 已增加 `008_coverage_gap_boundary` 数据库兼容迁移。
- 详细记录见 `step21-coverage-gap-agent.md`。

## Step 22：实现竞争分析 Agent

**状态：完成。**

- 已新增竞争分析 Agent 系统 Prompt、输入扩展和输出结构。
- 已接入坐标半径站点分页查询、连接器查询和数据版本过滤。
- 已实现距离权重、运营商分布、HHI、距离加权份额、充电类型/功率分组和竞争指数。
- 已实现服务空白、竞争风险、运营商集中度、无效坐标、过期数据和数据不足分类。
- 已接入运营商评价/差异化服务 RAG 检索、证据校验和分析结果保存。
- 详细记录见 `step22-competition-agent.md`。

## Step 23：实现候选选址 Agent

**状态：完成。**

- 已新增候选选址 Agent 系统 Prompt、输入扩展和输出结构。
- 已接入候选站点、区域和周边站点查询，按候选点范围限制数据读取。
- 已实现覆盖、交通、人口、竞争、建设条件、政策适配和数据可信度评分。
- 已实现可版本化权重、确定性总分、等级封顶、排序、扣分原因和推荐动作。
- 已接入选址规则/建设要求/审批条件 RAG 检索、证据校验和评分结果保存。
- 详细记录见 `step23-site-selection-agent.md`。

## Step 24：实现站点扩容 Agent

**状态：完成。**

- 已新增站点扩容 Agent 系统 Prompt、输入扩展和输出计划结构。
- 已接入站点、运营指标、故障、连接器和功率容量查询，并支持分页聚合。
- 已实现峰值利用率、故障集中度、可用容量、快慢充缺口和扩容预算的确定性计算。
- 已实现扩容优先级、可信度、前置条件、风险、缺失数据和 `WAITING_DATA` 状态。
- 已接入扩容规范/设备安全/配电/运维 RAG 检索、证据校验和扩容结果保存。
- 已复用高影响扩容方案的人工确认、批准恢复和拒绝流程。
- 详细记录见 `step24-expansion-agent.md`。

## Step 25：实现政策与补贴匹配 Agent

**状态：完成。**

- 已新增政策与补贴匹配 Agent 系统 Prompt、输入扩展和输出结构。
- 已接入候选站点字段及按区域、主体、政策类型、生效日期和数据版本筛选的政策条件查询。
- 已实现 JSON 条件、候选站点专属条件、有效期、申请截止日期和材料清单的逐项确定性匹配。
- 已区分 `PASS`、`PARTIAL`、`FAIL` 和 `UNKNOWN`，输出缺失字段、缺少材料、政策版本和截止日期。
- 已接入政策资格/材料/补贴 RAG 检索、证据校验和 `analysis.result.write` 结果保存。
- 详细记录见 `step25-policy-matching-agent.md`。

## Step 26：实现决策报告和人工确认

**状态：完成。**

- 已新增 `agent_report` 报告模型和 009 数据库兼容迁移，关联运行、数据版本、模型版本、规则版本和证据。
- 已实现报告草稿、待确认、已批准、已拒绝和已归档状态。
- 已实现统一报告详情，展示结论、计算结果、MySQL 业务数据和 RAG 原文证据。
- 已实现扩容、补贴匹配和高等级选址报告的人工确认、拒绝原因和审计记录。
- 已实现 Markdown 和 JSON 报告导出。
- 详细记录见 `step26-decision-reports-confirmation.md`。

## Step 27：实现 Vue 应用壳和路由菜单

**状态：完成。**

- 已创建 Vue 3、TypeScript、Vite 和 Element Plus 应用入口与构建配置。
- 已实现侧栏、顶栏、面包屑、页面内容区、全局通知和登录页。
- 已注册首页、站点、候选站点、5 个 Agent、RAG、运行记录和审计路由。
- 已实现按角色过滤菜单、登录 Token 保存、路由守卫、Token 失效清理和退出登录。
- 已实现 Axios Bearer Token、`X-Trace-ID`、统一错误和 `trace_id` 展示。
- 已实现 ECharts 容器的自适应与销毁机制，并为业务页预留加载、空数据、失败和权限状态承载区。
- 已通过 `npm run build` 构建验证。
- 详细记录见 `step27-vue-app-shell-routing.md`。

## Step 28：实现前端业务数据导入

**状态：完成。**

- 已新增数据导入菜单和数据集选择器，覆盖站点、连接器、运营指标、故障、候选站点和扩容案例。
- 已提供六类 CSV 模板下载，并补齐站点与连接器模板文件。
- 已支持 CSV、JSON 和 GeoJSON 文件上传、浏览器内预览和字段自动/手动映射。
- 已实现字段类型提示、必填校验、数字/坐标/日期/利用率校验和失败记录下载。
- 已实现导入确认、进度展示、批次统计、批次详情、回滚确认和权限不足状态。
- 已新增 `/imports` FastAPI 批次接口，确认后写入 `import_batch`、对应业务表和 `import_row_error`，支持批次查询、失败记录下载和回滚。
- 导入完成后会发出统一数据刷新事件，供后续地图、列表、Agent 和驾驶舱页面接入刷新。
- 已通过 `npm run build` 构建验证。
- 详细记录见 `step28-frontend-data-import.md`。
