# Step 35：执行 RAG 评测

**状态：完成。**

## 评测数据

- `evals/step35/rag_eval.json` 固定 7 个带类型、区域、版本、生效日期和 Agent 场景标签的文档，以及 10 个正向、过滤、版本、过期和无命中查询。
- 覆盖缺口、竞争分析、候选选址、站点扩容和政策匹配各自使用允许的文档类型，并包含区域/类型/版本过滤。
- `evals/step35/embedding_cases.json` 覆盖 Embedding 失败、重复入库、失败重试和批次重建/删除旧向量。

## 评测内容

`scripts/evaluate_rag.py` 使用生产 Chunk 清洗和切块实现，使用离线可复现的词项检索基线，输出：

- Recall@K、Hit Rate@K、MRR；
- 来源正确率（文档、类型、区域、版本和 Agent 场景）；
- 原文片段可定位率；
- 文档类型、区域、生效日期和版本过滤结果；
- 新旧版本选择、过期文档拦截和无命中 `EVIDENCE_INSUFFICIENT` 安全结果；
- Chunk 重建后的 Chunk ID、版本、位置和片段稳定性；
- Embedding 失败、重复批次、重试和重建生命周期；
- 每个 Agent 的业务文档类型检查，以及政策无证据时禁止生成政策结论的标记。

报告包含数据版本、模型/Embedding 配置、Prompt/规则版本、索引版本、Chunk 和检索参数、Fixture SHA-256 及逐查询结果，写入 `evals/step35/reports/latest.json`。

## 运行

```powershell
python scripts/evaluate_rag.py --strict
```

本次结果：10 个查询全部通过，Recall@3、Hit Rate@3、MRR、来源正确率和原文片段可定位率均为 1.0；Chunk 重建和 Embedding 生命周期检查全部通过。

无命中检索现在统一返回 `EVIDENCE_INSUFFICIENT`，避免下游 Agent 把空结果当作政策或运营结论依据。
