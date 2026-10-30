"""Registered Agent tool contracts used by Supervisor and tool execution layers."""

from __future__ import annotations

from app.agents.contracts import AgentType, ToolContract


TOOL_CONTRACTS: tuple[ToolContract, ...] = (
    ToolContract(name="region.query", category="mysql_query", description="查询区域、边界和区域政策关联", permission_code="station.read", input_schema="RegionQueryInput", output_schema="RegionQueryOutput", allowed_agent_types=["coverage_gap", "competition", "site_selection", "policy_matching"], retryable_error_codes=["DB_TIMEOUT", "DB_CONNECTION_ERROR"]),
    ToolContract(name="operator.query", category="mysql_query", description="查询运营商及其站点分布", permission_code="station.read", input_schema="OperatorQueryInput", output_schema="OperatorQueryOutput", allowed_agent_types=["competition"], retryable_error_codes=["DB_TIMEOUT", "DB_CONNECTION_ERROR"]),
    ToolContract(name="station.query", category="mysql_query", description="按区域、坐标和数据版本查询站点", permission_code="tool.station.query", input_schema="StationQueryInput", output_schema="StationQueryOutput", allowed_agent_types=["coverage_gap", "competition", "expansion"], retryable_error_codes=["DB_TIMEOUT", "DB_CONNECTION_ERROR"]),
    ToolContract(name="connector.query", category="mysql_query", description="查询连接器类型、数量和功率", permission_code="station.read", input_schema="ConnectorQueryInput", output_schema="ConnectorQueryOutput", allowed_agent_types=["coverage_gap", "competition", "expansion"], retryable_error_codes=["DB_TIMEOUT", "DB_CONNECTION_ERROR"]),
    ToolContract(name="operation.query", category="mysql_query", description="查询站点运营指标和利用率", permission_code="tool.operation.query", input_schema="OperationQueryInput", output_schema="OperationQueryOutput", allowed_agent_types=["coverage_gap", "expansion"], retryable_error_codes=["DB_TIMEOUT", "DB_CONNECTION_ERROR"]),
    ToolContract(name="fault.query", category="mysql_query", description="查询故障事件和恢复信息", permission_code="tool.fault.query", input_schema="FaultQueryInput", output_schema="FaultQueryOutput", allowed_agent_types=["expansion"], retryable_error_codes=["DB_TIMEOUT", "DB_CONNECTION_ERROR"]),
    ToolContract(name="candidate.query", category="mysql_query", description="查询候选站点及其完整度", permission_code="candidate.read", input_schema="CandidateQueryInput", output_schema="CandidateQueryOutput", allowed_agent_types=["site_selection", "policy_matching"], retryable_error_codes=["DB_TIMEOUT", "DB_CONNECTION_ERROR"]),
    ToolContract(name="coverage.analyze", category="deterministic_calculation", description="计算覆盖率、站点密度和缺口类型", permission_code="tool.coverage.analyze", input_schema="CoverageCalculationInput", output_schema="CoverageCalculationOutput", allowed_agent_types=["coverage_gap"], retryable_error_codes=["INVALID_INPUT"]),
    ToolContract(name="competition.analyze", category="deterministic_calculation", description="计算距离权重、集中度和竞争指数", permission_code="tool.competition.analyze", input_schema="CompetitionCalculationInput", output_schema="CompetitionCalculationOutput", allowed_agent_types=["competition"], retryable_error_codes=["INVALID_INPUT"]),
    ToolContract(name="site.score", category="deterministic_calculation", description="计算候选站点总分、分项分数和推荐等级", permission_code="tool.site.score", input_schema="SiteScoreInput", output_schema="SiteScoreOutput", risk_level="MEDIUM", allowed_agent_types=["site_selection"], retryable_error_codes=["INVALID_INPUT"]),
    ToolContract(name="expansion.plan", category="deterministic_calculation", description="计算扩容数量、预算和优先级", permission_code="tool.expansion.plan", input_schema="ExpansionPlanInput", output_schema="ExpansionPlanOutput", risk_level="HIGH", allowed_agent_types=["expansion"], requires_confirmation=True, confirmation_type="expansion_publish", retryable_error_codes=["INVALID_INPUT"]),
    ToolContract(name="policy.match", category="deterministic_calculation", description="按政策条件矩阵匹配资格和缺失材料", permission_code="tool.policy.match", input_schema="PolicyMatchInput", output_schema="PolicyMatchOutput", allowed_agent_types=["policy_matching"], retryable_error_codes=["INVALID_INPUT"]),
    ToolContract(name="rag.search", category="rag_search", description="执行混合 RAG 检索并返回可回溯证据", permission_code="tool.rag.search", input_schema="RagSearchRequest", output_schema="RagSearchResponse", allowed_agent_types=["coverage_gap", "competition", "site_selection", "expansion", "policy_matching"], retryable_error_codes=["EMBEDDING_REQUEST_FAILED", "CHROMA_REQUEST_FAILED", "DB_TIMEOUT"]),
    ToolContract(name="score.result.write", category="result_write", description="保存候选站点评分和证据", permission_code="tool.result.write", input_schema="SiteScoreOutput", output_schema="SiteScoreRecord", risk_level="MEDIUM", idempotency_required=True, allowed_agent_types=["site_selection"], retryable_error_codes=["DB_TIMEOUT", "DB_CONNECTION_ERROR"]),
    ToolContract(name="expansion.result.write", category="result_write", description="保存扩容方案并进入人工确认状态", permission_code="tool.result.write", input_schema="ExpansionOutput", output_schema="ExpansionPlanRecord", risk_level="HIGH", idempotency_required=True, requires_confirmation=True, confirmation_type="expansion_publish", allowed_agent_types=["expansion"], retryable_error_codes=["DB_TIMEOUT", "DB_CONNECTION_ERROR"]),
    ToolContract(name="analysis.result.write", category="result_write", description="保存覆盖、竞争或政策分析结果", permission_code="tool.result.write", input_schema="AgentOutputBase", output_schema="AgentResultRecord", risk_level="MEDIUM", idempotency_required=True, allowed_agent_types=["coverage_gap", "competition", "policy_matching"], retryable_error_codes=["DB_TIMEOUT", "DB_CONNECTION_ERROR"]),
)

TOOL_CONTRACT_MAP: dict[str, ToolContract] = {contract.name: contract for contract in TOOL_CONTRACTS}


def get_tool_contract(tool_name: str) -> ToolContract | None:
    return TOOL_CONTRACT_MAP.get(tool_name)


def contracts_for_agent(agent_type: AgentType) -> list[ToolContract]:
    return [contract for contract in TOOL_CONTRACTS if agent_type in contract.allowed_agent_types]
