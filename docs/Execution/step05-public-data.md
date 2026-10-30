# Step 5：下载并登记公开充电站数据

## 执行结果

- 数据源：美国能源部 Alternative Fuels Data Center（AFDC）/ National Laboratory of the Rockies。
- 官方数据接口：`https://developer.nlr.gov/api/alt-fuel-stations/v1.csv`。
- 查询范围：`fuel_type=ELEC`、`access=public`、`status=E`、`country=US`、`state=CA`、`limit=all`。
- 首批演示区域：美国加州（`CA`）。
- 下载时间：2026-10-29（America/Los_Angeles）。
- 原始文件：`data/raw/public/afdc_electric_stations_ca_2026-10-29.csv`。
- 文件大小：6,995,939 bytes。
- 行数：20,369 条站点记录。
- SHA-256：`06a32bcf522dca77910eb264eb1fea5d9dc6888e8ccdd6c777e6607dbf41020d`。

## MySQL 登记

已创建并写入 Step 5 所需的最小业务表：

- `import_batch`：批次 `afdc-public-ca-2026-10-29-06a32bcf522dca77`，批次 ID `2`。
- `region`：`CA / California`。
- `operator`：65 个公开网络/运营商名称。
- `charging_station`：20,369 条站点记录。
- `charging_connector`：20,677 条按 `LEVEL1`、`LEVEL2`、`DC_FAST`、`OTHER` 分类的连接器记录。

所有记录保留 `source_type=public`、来源 URL、原始文件、数据版本和 `import_batch_id`。外部站点主键为 AFDC `ID`，站点快照唯一键为 `external_station_id + data_version`，重复执行不会重复插入站点。

## RAG 文本和向量登记

已生成两份 UTF-8 Markdown 文档：

- `rag_docs/business_rules/afdc_public_station_data.md`：来源、查询条件、快照统计、业务映射和使用限制。
- `rag_docs/business_rules/afdc_station_field_dictionary.md`：AFDC 字段字典摘录和 ChargeOps 字段用途。

两份文档已写入：

- MySQL `rag_document`：2 条文档登记。
- MySQL `rag_chunk`：3 个 Chunk，包含字符位置、版本、来源和 Chroma ID。
- Chroma 集合 `chargeops_documents`：3 个向量，Embedding 模型为 `BAAI/bge-m3`。

## 质量检查

- 有效经纬度：20,369 / 20,369。
- 外部站点 ID 缺失：0。
- 外部站点 ID 重复：0。
- 原始文件 SHA-256 与清单一致。
- 使用外部 Embedding 生成查询向量后，Chroma 能返回两份 AFDC 文档及其来源元数据。

## 可重复执行

执行脚本：`scripts/register_afdc_public_data.py`。

脚本会下载或复用原始文件，生成规范化 CSV、来源清单、Markdown 文档，并执行 MySQL 和 Chroma 的幂等登记。

## 来源和使用说明

- 数据下载页：`https://afdc.energy.gov/data_download`
- 字段参考：`https://afdc.energy.gov/data_download/alt_fuel_stations_format`
- AFDC 下载条款允许数据用于任何目的，但数据按现状提供，需遵守官方免责声明和署名限制。
- 该快照不包含订单、利用率、故障、预算或电力容量，不能单独作为投资、审批或扩容批准依据。
