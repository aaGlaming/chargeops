# ChargeOps MySQL 数据字典

本文是 Step 8 的目标数据模型。所有可追溯业务数据默认保留 `source_type`、来源 URL/文件、`data_version`、`import_batch_id`、创建时间和更新时间；软删除表额外保留 `deleted_at`。`source_type` 只允许 `public`、`user_upload`、`synthetic`、`agent`。

## 认证与权限

| 表 | 用途 | 主键 | 关键字段/约束 |
|---|---|---|---|
| `users` | 用户和登录状态 | `id` | `username` 唯一；保存密码哈希、Token 版本、软删除时间 |
| `roles` | 角色定义 | `id` | `role_code` 唯一；对应运营分析师、选址规划师、运维负责人、政策管理员、系统管理员、审计人员 |
| `permissions` | API、菜单和工具权限 | `id` | `permission_code` 唯一；`resource + action` 可检索 |
| `user_role` | 用户-角色关联 | `(user_id, role_id)` | 记录分配人和分配时间 |
| `role_permission` | 角色-权限关联 | `(role_id, permission_id)` | 记录授权人和授权时间 |
| `user_data_scope` | 用户可读/可写的数据集和区域范围 | `(user_id, region_code, dataset_type)` | 控制数据集读写和区域边界；`*` 表示全部区域 |

## 数据导入与业务主数据

| 表 | 用途 | 主键/唯一键 | 关键字段 |
|---|---|---|---|
| `import_batch` | 文件导入批次、哈希、统计和回滚状态 | `id`；`batch_key` 唯一 | 数据集类型、来源类型、SHA-256、版本、成功/失败/跳过行数、状态 |
| `region` | 行政区、商圈、园区或自定义区域 | `id`；`region_code + data_version` | 父子层级、GeoJSON 边界、来源和批次 |
| `operator` | 运营商/网络品牌 | `id`；名称+版本唯一 | 运营商代码、名称、网站和来源 |
| `charging_station` | 充电站主数据 | `id`；外部站点 ID/外部键+版本唯一 | 区域、运营商、地址、坐标、状态、访问类型、充电类型、总连接器数；外部键支持 `SYN-ST-*` 等非数字来源 ID |
| `charging_connector` | 站点连接器分类和功率 | `id`；站点+类型+版本唯一 | `connector_type`、数量、功率、状态 |

## 运营、候选点和政策

| 表 | 用途 | 关键字段 |
|---|---|---|
| `station_operation_metric` | 日/小时充电运营指标 | 站点、日期、小时、时区、充电次数、电量、峰值功率、占用率、平均时长；站点+时间+版本唯一 |
| `station_fault_event` | 故障和恢复事件 | 站点、外部故障 ID、故障类型、严重等级、开始/恢复时间、影响连接器、状态 |
| `candidate_site` | 候选站点及建设条件 | 外部候选 ID、坐标、面积、停车位、电力容量、预算、交通指数、人口密度、计划开放日期、数据状态 |
| `policy_condition` | 建设、补贴、消防、停车和并网政策条件 | 政策代码/版本、区域、申请主体、条件键/操作符/JSON 值、材料、金额、生效日期、截止日期 |
| `site_score` | 候选点确定性评分结果 | 候选点、运行 ID、规则版本、覆盖/交通/竞争/建设/政策/可信度分项分数、总分、等级、扣分和证据 |
| `expansion_plan` | 站点扩容建议 | 外部案例 ID、站点、运行 ID、现有/新增连接器、占用率、故障数、电力容量、预算、优先级、前置条件、确认状态 |

## Agent、RAG 和审计

| 表 | 用途 | 关键字段 |
|---|---|---|
| `agent_run` | Agent 运行状态和状态快照 | UUID 运行 ID、Agent 类型、请求用户、输入、数据/Prompt/模型版本、状态、停止原因、证据摘要、确认状态 |
| `tool_call` | Agent 工具轨迹 | 运行 ID、序号、工具名、权限码、风险等级、幂等键、输入/输出摘要、错误码、可重试标记、耗时 |
| `rag_document` | Markdown 文档和向量化状态 | 文档键、标题、类型、来源、区域、版本、生效日期、文件哈希、解析/向量状态、Embedding 模型 |
| `rag_chunk` | 文档 Chunk 和 Chroma 对应关系 | 文档、Chunk 序号、标题路径、原文字符位置、Chroma 集合/ID、Embedding 模型、元数据 |
| `rag_document_section` | Markdown 解析后的标题、段落、列表、表格和条款区块 | `(document_id, section_index)`；保存区块类型、标题路径、原文位置和解析元数据 |
| `rag_chunk_batch` | 文本清洗和切块预览/重建批次 | 文档版本、清洗版本、目标/重叠 token、批次状态、Chunk 数、校验失败数和创建人 |
| `rag_embedding_batch` | Embedding 和 Chroma 向量化批次 | 模型、模型版本、参数、批次状态、成功/失败/待重试数量、错误和时间 |
| `rag_embedding_item` | 批次内 Chunk 的向量化状态 | Chunk、Chroma ID、状态、尝试次数、向量维度和失败原因 |
| `rag_search_log` | RAG 检索运行记录 | 查询、改写查询、Agent 场景、过滤条件、召回/命中数量、Chunk ID、状态和运行 ID |
| `agent_run_event` | Agent 模型调用和人工确认事件 | 运行 ID、事件序号、事件类型、模型/确认信息、输入/输出摘要、错误、重试和耗时 |
| `agent_report` | 决策报告、确认状态和导出数据 | 报告/运行 ID、报告类型、状态、结论、计算结果、MySQL 数据、RAG 证据、版本、确认人和确认意见 |
| `audit_log` | 不可变审计事件 | 操作人、动作、资源、请求/Trace/运行/批次 ID、前后状态、严重级别、发生时间；不设置更新字段 |

## 关系与索引原则

- 区域、运营商、站点、连接器形成主数据链路；站点是运营指标、故障和扩容方案的父对象。
- 候选站点连接评分结果；政策条件按区域和生效时间过滤。
- Agent 运行连接工具调用、评分和扩容计划；高影响结果通过确认字段进入人工审批流程。
- RAG 原文状态在 MySQL，向量内容在 Chroma；`rag_chunk.chroma_id` 是两者的稳定关联。
- 所有外部导入表按批次、来源、版本建立索引；站点坐标、状态、区域和运营商是主要查询索引。
- 软删除用于业务对象；`audit_log` 只追加，不允许更新或删除。

## 状态与回滚

- 导入批次：`PENDING` → `VALIDATING` → `IMPORTING` → `IMPORTED`，异常进入 `FAILED`；回滚状态独立记录。
- Agent 运行：`PENDING`、`RUNNING`、`WAITING_CONFIRMATION`、`COMPLETED`、`FAILED`、`BLOCKED`、`CANCELLED`。
- 扩容和高等级评分保留原始 Agent 结果，确认/拒绝只改变确认状态并追加审计记录。
- `import_batch_id` 是整批回滚和失败行修复的边界；重复文件用 `batch_key` 和 SHA-256 去重。
