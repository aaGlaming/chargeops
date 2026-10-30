# Step 39：备份和恢复验证

**状态：完成。**

## 备份内容

`scripts/backup_chargeops.py` 生成带 UTC 时间戳的备份目录，内容包括：

- MySQL `mysqldump` 结构、业务数据、导入批次、Agent 运行、工具调用和审计日志，并附表行数快照。
- Chroma 持久化目录，以及 RAG 原始 Markdown、清洗结果、Manifest、模板、评测结果和 `.env.example`。
- 每个备份文件的 SHA-256 清单 `SHA256SUMS.txt`。

默认 Chroma 目录为 `data/chroma`；Docker 或独立 Chroma 服务使用其他持久化目录时，通过 `--chroma-dir` 或 `CHROMA_DATA_DIR` 指定实际目录。备份目录在 `.gitignore` 中，不会把业务快照、密钥或真实上传文件提交到仓库。

## 恢复验证

执行：

```powershell
python scripts/backup_chargeops.py --output-root backups/step39 --chroma-dir <实际 Chroma 持久化目录>
python scripts/restore_chargeops.py <备份目录> --restore-dir restore/step39/<时间戳> --api-url http://127.0.0.1:8010 --username <验收账号> --password <通过环境变量或安全输入提供>
```

恢复脚本执行以下检查：

- 将归档文件恢复到独立目录并验证全部 SHA-256。
- 在业务数据库内创建带 `step39_restore_` 前缀的影子表，导入完整 MySQL dump，核对 31 张表和关键业务行数，然后关闭外键检查清理影子表；业务表不被删除或覆盖。
- 从恢复目录启动临时 Chroma 实例，验证 heartbeat、collection 和持久化索引可读取。
- 通过 API 重新执行一次 RAG 混合检索和一次候选选址 Agent，确认 RAG 命中且 Agent 返回 `COMPLETED`。

## 实际结果

本次备份包含 31 张 MySQL 表、59 个校验文件；恢复目录包含 58 个文件，SHA-256 失败数为 0。MySQL 影子恢复验证 31/31 张表，Chroma 恢复实例读取 1 个 collection，RAG 命中 3 条，候选选址 Agent 运行完成。

报告：`evals/step39/reports/latest.json`。
