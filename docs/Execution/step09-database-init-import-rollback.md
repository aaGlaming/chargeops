# Step 9：实现数据库初始化、导入和回滚

## 执行结果

- 初始化脚本：`scripts/init_database.py`
- 导入脚本：`scripts/import_data.py`
- 回滚脚本：`scripts/rollback_import.py`
- 已执行目标 DDL，并保留 Step 5 已存在的公开数据。
- 已创建 `schema_migration` 和 `import_row_error` 工作流表。
- 当前数据库表数量：23 张（21 张模型表 + 2 张工作流表）。

## 初始化与兼容迁移

初始化脚本会：

- 执行 `infra/mysql/001_initial_schema.sql` 中的目标表定义。
- 对 Step 5 临时表补充 `dataset_type`、成功/失败统计、回滚状态和外部站点键等兼容字段。
- 为字符串外部 ID（例如 `SYN-ST-001`）建立 `charging_station.external_station_key`。
- 记录模型迁移版本和 DDL SHA-256 到 `schema_migration`。
- 不删除已有业务数据，重复执行不会重复创建表或迁移记录。

## 公开数据导入

- 输入：Step 7 清洗文件 `afdc_electric_stations_ca_2026-10-29_cleaned.csv`。
- 复用原 AFDC 导入批次 ID `2`，避免与 Step 5 已导入站点重复。
- 站点成功更新：20,355 条。
- 连接器分类成功更新：20,662 条。
- 失败行：14 条，来自 Step 7 识别的重复站点指纹。
- 批次状态：`PARTIAL`，失败文件路径写入 `import_batch.failure_report_file`。

## 合成数据导入

- 批次：`synthetic-demo-2026-10-29-v1`，数据库批次 ID `3`。
- 总输入：559 条。
- 成功：559 条；失败：0 条。
- 写入站点：12 条。
- 写入候选站点：12 条。
- 写入运营指标：504 条。
- 写入故障：31 条。
- 写入扩容方案：8 条。
- 写入政策条件：4 条。
- 批次状态：`IMPORTED`。

导入使用业务唯一键和 `ON DUPLICATE KEY UPDATE`，重复执行不会重复插入站点、指标、故障、候选点、政策或扩容数据。

## 回滚验证

执行过一次合成批次回滚演练：

```powershell
python scripts/rollback_import.py --batch-id 3 --confirm
```

回滚删除 572 条批次关联记录，并保留 `import_batch` 记录和回滚状态；随后重新执行合成导入，559 条记录全部恢复，最终状态为 `IMPORTED`、`rollback_status=NOT_REQUESTED`。

回滚脚本默认要求 `--confirm`，可先使用 `--dry-run` 查看各表待删除行数。

## 失败行和事务规则

- 行级错误写入 `import_row_error`，保存批次、文件、行号、字段、错误码、错误信息和原始 JSON。
- 可修复的行错误允许批次进入 `PARTIAL`，成功行正常写入。
- 数据库异常会回滚当前事务，并将批次标记为 `FAILED`。
- 批次回滚按连接器、指标、故障、扩容、站点、候选点、政策、运营商和区域顺序删除，避免外键冲突。
