# Step 8：设计 MySQL 数据模型

## 执行结果

- 已完成认证权限、导入批次、区域、运营商、站点、连接器、运营指标、故障、候选站点、政策、评分、扩容、Agent、工具调用、RAG 和审计表设计。
- 已为业务数据统一设计 `source_type`、来源、数据版本、导入批次、时间戳和软删除字段。
- 已为站点、候选点、区域、Agent 运行、导入批次、RAG 文档和审计查询设计索引与唯一约束。
- 已定义外键、批次回滚边界、Agent 高影响确认字段和不可变审计日志规则。
- 已输出目标 DDL：`infra/mysql/001_initial_schema.sql`。
- 已输出 ER 图：`docs/architecture/chargeops-mysql-erd.mmd`。
- 已输出字段数据字典：`docs/data-dictionary.md`。

## 与当前数据库的关系

Step 5 为公开数据登记创建了最小导入表，当前数据库中已有 `region`、`operator`、`charging_station`、`charging_connector`、`import_batch`、`rag_document` 和 `rag_chunk`。Step 8 的 DDL 是完整目标模型，不直接覆盖这些临时表；Step 9 将通过迁移脚本补齐字段、约束、外键和新增表。

## 设计决策

- 使用 BIGINT 自增主键保存内部关系，保留 AFDC 或用户文件中的外部 ID。
- `source_type` 使用受限枚举值，禁止把合成数据伪装成公开或真实运营数据。
- 所有需要重跑或回滚的导入由 `import_batch` 管理，文件 SHA-256 与 `batch_key` 防止重复插入。
- RAG 文本和解析状态在 MySQL，向量和向量检索在 Chroma，通过 `rag_chunk.chroma_id` 关联。
- 评分分项和政策条件使用 JSON 保存可变明细，同时保留可筛选的核心数值列。
- `site_score` 和 `expansion_plan` 保留 `run_id`，确保结果可以回到 Agent 输入、工具轨迹和证据。
- 审计日志只追加，不提供业务更新路径；高影响结果必须保存确认人、时间和意见/拒绝原因。

## Step 9 衔接

下一步将把 DDL 拆分为可执行迁移，初始化空库，补齐当前 Step 5 临时表，并实现公开数据、合成数据和用户上传数据的校验、导入、失败行记录和回滚。
