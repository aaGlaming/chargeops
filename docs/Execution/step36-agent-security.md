# Step 36：Agent 评测和安全验证

执行日期：2026-10-30  
评测脚本：`scripts/evaluate_agents_security.py`  
报告：`evals/step36/reports/latest.json`  
安全问题清单：`evals/step36/security_findings.json`

## 覆盖范围

- 五个 Agent 的工具路由、MySQL 查询契约、RAG 检索契约、输入 Schema、输出 Schema 和业务字段完整性。
- Step 34 的 10 个确定性业务样例，覆盖覆盖缺口、竞争指数、候选点评分、扩容优先级、政策匹配，以及缺失站点/候选点/运营指标/政策和过期数据。
- 提示注入、恶意 Markdown、伪造政策、角色越权、敏感信息脱敏、重复调用、超时、模型/Embedding/Chroma/MySQL 依赖故障。
- 高影响扩容建议的风险等级、幂等写入和人工确认状态。

## 结果

`python scripts/evaluate_agents_security.py --strict` 结果为 **PASS**：65 项检查全部通过。

发现并修复 1 个高严重级别设计问题：Agent 状态转换原先使用 `model_copy(update=...)`，状态补丁不会重新执行 Pydantic 校验，可能写入未知字段或非法状态。现在合并补丁后统一使用 `AgentStateSnapshot.model_validate`，拒绝未知字段、非法枚举并限制补丁字段数量。回归结果记录在 `SEC-STEP36-001`。

## 运行方式

```powershell
python scripts/evaluate_agents_security.py --strict
```

脚本只使用版本化 Gold 数据和离线契约检查，不调用模型、MySQL 或 Chroma；依赖故障场景通过异常映射、重试标志、超时边界和幂等冲突路径验证。
