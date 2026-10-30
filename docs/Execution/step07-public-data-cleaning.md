# Step 7：建立公开数据清洗和统一映射

## 执行结果

- 输入文件：`data/raw/public/afdc_electric_stations_ca_2026-10-29.csv`
- 输入行数：20,369
- 清洗批次：`clean-public-afdc-ca-2026-10-29-v1`
- 关联导入批次：`afdc-public-ca-2026-10-29-06a32bcf522dca77`
- 输出清洗行：20,355
- 失败行：14
- 原始 CSV 未修改。

## 输出文件

- 清洗结果：`data/processed/afdc_electric_stations_ca_2026-10-29_cleaned.csv`
- 失败行：`data/processed/afdc_electric_stations_ca_2026-10-29_failed.csv`
- 字段映射：`data/manifests/afdc_electric_stations_ca_2026-10-29_field_mapping.json`
- 质量报告：`data/manifests/afdc_electric_stations_ca_2026-10-29_quality_report.json`
- 清洗清单：`data/manifests/afdc_electric_stations_ca_2026-10-29_cleaning_manifest.json`

## 统一映射

- 站点名称、运营商和地址执行 Unicode NFKC、去首尾空白和连续空白合并。
- 空运营商统一为 `Non-Networked`。
- `Status Code` 映射为 `OPEN`、`PLANNED`、`TEMPORARILY_UNAVAILABLE` 或 `UNKNOWN`。
- `Access Code` 映射为大写的 `PUBLIC`、`PRIVATE`、`RESTRICTED` 或 `UNKNOWN`。
- Level 1、Level 2、DC Fast 和 Other 连接器数量转为非负整数，并生成总数量。
- 充电类型统一为 `AC_LEVEL1`、`AC_LEVEL2`、`DC_FAST`、`OTHER` 的管道分隔值。
- 日期统一为 ISO-8601 日期；`Updated At` 统一为 UTC `Z` 结尾的 ISO-8601 时间。
- `effective_date` 按最后确认日期、更新时间日期、开放日期顺序回填。
- AFDC 当前站点快照没有每个连接器的 kW 字段，因此 `power_kw` 保持空值并标记 `NOT_PROVIDED`，不进行未经证实的功率推断。

## 质量检查

- 坐标范围校验：20,355 条通过；0 条坐标错误。
- 外部站点 ID 重复：0 条。
- 站点名称/地址/坐标指纹重复：14 条，写入失败行文件，未静默保留重复。
- 连接器复合键重复：0 条；复合键为 `external_station_id + canonical connector type`。
- 站点状态：20,355 条 `OPEN`。
- 访问类型：20,355 条 `PUBLIC`。
- 所有清洗结果保留原始外部 ID、来源 URL、原始文件、`import_batch_id` 和数据版本。

## 可重复执行

执行脚本：`scripts/clean_public_afdc_data.py`。

脚本每次从 `data/raw/public` 读取原始文件，只覆盖 `data/processed` 和 `data/manifests` 中同名处理产物，不会修改原始数据。清洗结果将在 Step 9 进入正式导入校验和批次导入流程。
