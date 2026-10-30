"""Authorization catalog and role/data-scope policies."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionDefinition:
    code: str
    resource: str
    action: str
    description: str


ROLE_DEFINITIONS: tuple[tuple[str, str, str], ...] = (
    ("OPS_ANALYST", "运营分析师", "查询站点、运营指标和覆盖/竞争分析结果"),
    ("SITE_PLANNER", "选址规划师", "管理候选站点并执行选址评分"),
    ("OPS_LEAD", "运维负责人", "管理运营数据、故障和扩容方案"),
    ("POLICY_ADMIN", "政策管理员", "管理政策文档、条件和向量索引"),
    ("SYSTEM_ADMIN", "系统管理员", "管理用户、角色、权限和全部业务资源"),
    ("AUDITOR", "审计人员", "只读查看业务、运行和审计记录"),
)


PERMISSION_DEFINITIONS: tuple[PermissionDefinition, ...] = (
    PermissionDefinition("menu.dashboard", "menu", "read", "查看业务驾驶舱"),
    PermissionDefinition("menu.stations", "menu", "read", "查看站点和连接器菜单"),
    PermissionDefinition("menu.candidates", "menu", "read", "查看候选站点菜单"),
    PermissionDefinition("menu.agent.coverage", "menu", "read", "使用覆盖缺口菜单"),
    PermissionDefinition("menu.agent.competition", "menu", "read", "使用竞争分析菜单"),
    PermissionDefinition("menu.agent.site_selection", "menu", "read", "使用候选选址菜单"),
    PermissionDefinition("menu.agent.expansion", "menu", "read", "使用站点扩容菜单"),
    PermissionDefinition("menu.agent.policy", "menu", "read", "使用政策匹配菜单"),
    PermissionDefinition("menu.rag", "menu", "read", "使用 RAG 菜单"),
    PermissionDefinition("menu.imports", "menu", "read", "使用数据导入菜单"),
    PermissionDefinition("menu.audit", "menu", "read", "查看审计菜单"),
    PermissionDefinition("menu.admin", "menu", "read", "使用系统管理菜单"),
    PermissionDefinition("station.read", "station", "read", "读取充电站和连接器"),
    PermissionDefinition("metric.read", "station_metric", "read", "读取站点运营指标"),
    PermissionDefinition("fault.read", "station_fault", "read", "读取站点故障"),
    PermissionDefinition("fault.write", "station_fault", "write", "创建和更新站点故障"),
    PermissionDefinition("candidate.read", "candidate_site", "read", "读取候选站点"),
    PermissionDefinition("candidate.write", "candidate_site", "write", "新增、修改和删除候选站点"),
    PermissionDefinition("policy.read", "policy", "read", "读取政策条件"),
    PermissionDefinition("policy.write", "policy", "write", "新增和修改政策条件"),
    PermissionDefinition("expansion.read", "expansion_plan", "read", "读取扩容方案"),
    PermissionDefinition("expansion.write", "expansion_plan", "write", "创建和修改扩容方案"),
    PermissionDefinition("import.read", "import_batch", "read", "读取导入批次"),
    PermissionDefinition("import.write", "import_batch", "write", "创建和回滚导入批次"),
    PermissionDefinition("rag.read", "rag_document", "read", "读取 RAG 文档和 Chunk"),
    PermissionDefinition("rag.write", "rag_document", "write", "上传和编辑 RAG 文档"),
    PermissionDefinition("rag.document.delete", "rag_document", "delete", "删除 RAG 文档"),
    PermissionDefinition("rag.vector.rebuild", "rag_vector", "rebuild", "重建 RAG 向量"),
    PermissionDefinition("report.read", "report", "read", "读取 Agent 报告"),
    PermissionDefinition("report.confirm", "report", "confirm", "确认或拒绝高影响报告"),
    PermissionDefinition("agent.run.read", "agent_run", "read", "读取 Agent 运行和工具轨迹"),
    PermissionDefinition("agent.run.start", "agent_run", "start", "启动 Agent 运行"),
    PermissionDefinition("audit.read", "audit_log", "read", "读取审计日志"),
    PermissionDefinition("user.manage", "user", "manage", "管理用户"),
    PermissionDefinition("permission.manage", "permission", "manage", "管理角色和权限"),
    PermissionDefinition("dataset.public.read", "dataset.public", "read", "读取公开数据集"),
    PermissionDefinition("dataset.user_upload.read", "dataset.user_upload", "read", "读取用户上传数据集"),
    PermissionDefinition("dataset.user_upload.write", "dataset.user_upload", "write", "写入用户上传数据集"),
    PermissionDefinition("dataset.synthetic.read", "dataset.synthetic", "read", "读取合成数据集"),
    PermissionDefinition("dataset.synthetic.write", "dataset.synthetic", "write", "写入合成数据集"),
    PermissionDefinition("tool.station.query", "agent_tool", "station.query", "调用站点查询工具"),
    PermissionDefinition("tool.operation.query", "agent_tool", "operation.query", "调用运营指标查询工具"),
    PermissionDefinition("tool.fault.query", "agent_tool", "fault.query", "调用故障查询工具"),
    PermissionDefinition("tool.coverage.analyze", "agent_tool", "coverage.analyze", "调用覆盖缺口工具"),
    PermissionDefinition("tool.competition.analyze", "agent_tool", "competition.analyze", "调用竞争分析工具"),
    PermissionDefinition("tool.site.score", "agent_tool", "site.score", "调用候选点评分工具"),
    PermissionDefinition("tool.expansion.plan", "agent_tool", "expansion.plan", "调用扩容规划工具"),
    PermissionDefinition("tool.policy.match", "agent_tool", "policy.match", "调用政策匹配工具"),
    PermissionDefinition("tool.rag.search", "agent_tool", "rag.search", "调用 RAG 检索工具"),
    PermissionDefinition("tool.rag.rebuild", "agent_tool", "rag.rebuild", "调用 RAG 向量重建工具"),
    PermissionDefinition("tool.result.write", "agent_tool", "result.write", "写入 Agent 结果"),
    PermissionDefinition("confirmation.document.delete", "confirmation", "document.delete", "确认删除文档"),
    PermissionDefinition("confirmation.vector.rebuild", "confirmation", "vector.rebuild", "确认重建向量"),
    PermissionDefinition("confirmation.data.overwrite", "confirmation", "data.overwrite", "确认覆盖数据"),
    PermissionDefinition("confirmation.expansion.publish", "confirmation", "expansion.publish", "确认发布扩容方案"),
)


_COMMON_READ = {
    "menu.dashboard", "menu.stations", "menu.candidates", "station.read", "metric.read", "fault.read",
    "candidate.read", "policy.read", "expansion.read", "report.read", "agent.run.read", "dataset.public.read",
    "dataset.user_upload.read", "dataset.synthetic.read", "tool.station.query", "tool.operation.query",
    "tool.fault.query", "tool.rag.search",
}


ROLE_PERMISSION_CODES: dict[str, frozenset[str]] = {
    "OPS_ANALYST": frozenset(_COMMON_READ | {
        "menu.agent.coverage", "menu.agent.competition", "tool.coverage.analyze", "tool.competition.analyze", "agent.run.start",
    }),
    "SITE_PLANNER": frozenset(_COMMON_READ | {
        "menu.agent.coverage", "menu.agent.competition", "menu.agent.site_selection", "candidate.write",
        "tool.coverage.analyze", "tool.competition.analyze", "tool.site.score", "tool.result.write", "agent.run.start",
    }),
    "OPS_LEAD": frozenset(_COMMON_READ | {
        "menu.agent.coverage", "menu.agent.competition", "menu.agent.expansion", "candidate.write",
        "expansion.write", "import.read", "import.write", "dataset.user_upload.write", "dataset.synthetic.write",
        "tool.coverage.analyze", "tool.competition.analyze", "tool.expansion.plan", "tool.result.write",
        "fault.write",
        "confirmation.data.overwrite", "confirmation.expansion.publish", "agent.run.start",
    }),
    "POLICY_ADMIN": frozenset(_COMMON_READ | {
        "menu.agent.policy", "menu.rag", "menu.imports", "policy.write", "rag.read", "rag.write",
        "rag.document.delete", "rag.vector.rebuild", "tool.policy.match", "tool.rag.rebuild", "tool.result.write",
        "confirmation.document.delete", "confirmation.vector.rebuild", "agent.run.start",
    }),
    "AUDITOR": frozenset(_COMMON_READ | {"menu.audit", "audit.read", "rag.read", "import.read"}),
}


ALL_PERMISSION_CODES = frozenset(definition.code for definition in PERMISSION_DEFINITIONS)
ROLE_PERMISSION_CODES["SYSTEM_ADMIN"] = ALL_PERMISSION_CODES


DEFAULT_DATASET_READ: dict[str, frozenset[str]] = {
    "OPS_ANALYST": frozenset({"public", "user_upload", "synthetic"}),
    "SITE_PLANNER": frozenset({"public", "user_upload", "synthetic"}),
    "OPS_LEAD": frozenset({"public", "user_upload", "synthetic"}),
    "POLICY_ADMIN": frozenset({"public", "user_upload", "synthetic"}),
    "AUDITOR": frozenset({"public", "user_upload", "synthetic", "agent"}),
    "SYSTEM_ADMIN": frozenset({"public", "user_upload", "synthetic", "agent"}),
}

DEFAULT_DATASET_WRITE: dict[str, frozenset[str]] = {
    "OPS_ANALYST": frozenset(),
    "SITE_PLANNER": frozenset({"user_upload", "agent"}),
    "OPS_LEAD": frozenset({"user_upload", "synthetic", "agent"}),
    "POLICY_ADMIN": frozenset({"user_upload", "agent"}),
    "AUDITOR": frozenset(),
    "SYSTEM_ADMIN": frozenset({"public", "user_upload", "synthetic", "agent"}),
}


HIGH_RISK_CONFIRMATION_PERMISSIONS: dict[str, str] = {
    "document_delete": "confirmation.document.delete",
    "vector_rebuild": "confirmation.vector.rebuild",
    "data_overwrite": "confirmation.data.overwrite",
    "expansion_publish": "confirmation.expansion.publish",
}
