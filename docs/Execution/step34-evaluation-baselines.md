# Step 34：建立评测数据集和确定性基线

**状态：完成。**

## 评测资产

- `evals/step34/agent_gold.json`：覆盖缺口、竞争分析、候选选址、站点扩容和政策匹配五类 Agent 的固定输入、业务上下文、Gold 关键字段、预期输出结构和拒绝条件；每类包含正常样例和数据不足样例。
- `evals/step34/rag_gold.json`：3 个版本化 RAG 文档、4 个查询、文档类型/区域/版本过滤、期望文档、期望原文片段和无命中证据不足样例。
- `evals/step34/import_cases.json`：导入正常、重复外部 ID、坐标越界、连接器外键缺失和必填字段缺失样例。
- `evals/step34/versions.json`：固定数据、Prompt、模型、Embedding、索引和确定性规则版本；评测使用离线模型/Embedding 占位配置，不访问外部服务。
- `evals/step34/failure_attribution.json`：每个预期失败样例的错误类别、根因、责任方、修复状态和修复动作。

## 确定性基线

`scripts/evaluate_deterministic_baseline.py` 直接调用生产 Agent 的确定性函数，执行：

- 距离、覆盖率、站点密度和时间缺口；
- 距离加权竞争指数、HHI、运营商分布和功率分组；
- 候选站点评分、排序、推荐等级和缺失字段降级；
- 扩容连接器数量、预算、功率调整和优先级；
- 政策条件逐项匹配、PASS/PARTIAL/FAIL/UNKNOWN、材料缺口和版本。

脚本还验证 Gold 结构、必需字段、停止原因、拒绝条件、版本清单、RAG 原文片段和导入错误码，并输出带 Fixture SHA-256、版本、分 Agent 通过率、确定性指标和失败归因的 `evals/step34/reports/latest.json`。

## 运行

```powershell
python scripts/evaluate_deterministic_baseline.py --strict
```

本次基线结果：15 个样例全部通过，覆盖 5 个 Agent、4 个 RAG 查询和 5 个导入校验场景。
