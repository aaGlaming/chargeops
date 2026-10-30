"""Supervisor orchestration and LangGraph loop control for the five Agents."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import langchain
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, StateGraph
from langchain_core.globals import set_debug
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agents.contracts import AgentError, AgentEvidence, AgentGraphState, ConfirmationRecord, ModelCallRecord
from app.agents.coverage_gap import COVERAGE_GAP_SYSTEM_PROMPT
from app.agents.competition import COMPETITION_SYSTEM_PROMPT
from app.agents.site_selection import SITE_SELECTION_SYSTEM_PROMPT
from app.config import Settings
from app.errors import AppError
from app.schemas.agents import SupervisorExecuteRequest
from app.services.agent_runs import (
    get_agent_run,
    record_agent_event,
    transition_agent_run,
)
from app.services.auth import UserContext, require_high_risk_confirmation
from app.tools.executor import execute_tool


# LangGraph 1.2 can run with an older LangChain 1.3 installation, but that
# combination does not initialize the legacy `langchain.debug` flag itself.
# Set it explicitly so graph invocation remains compatible with the lockfile
# and with environments that already provide the attribute.
if not hasattr(langchain, "debug"):
    set_debug(False)


TERMINAL = {"COMPLETED", "FAILED", "BLOCKED", "CANCELLED"}


@dataclass(frozen=True)
class SupervisorLimits:
    max_model_calls: int = 3
    max_tool_calls: int = 20
    max_loop_iterations: int = 8
    max_duration_seconds: float = 120.0

    @classmethod
    def from_request(cls, request: SupervisorExecuteRequest | None) -> "SupervisorLimits":
        if request is None:
            return cls()
        return cls(
            max_model_calls=request.max_model_calls,
            max_tool_calls=request.max_tool_calls,
            max_loop_iterations=request.max_loop_iterations,
            max_duration_seconds=request.max_duration_seconds,
        )


@dataclass
class SupervisorContext:
    session: Session
    settings: Settings
    user: UserContext
    run_id: str
    limits: SupervisorLimits
    started_at: datetime


def _decode(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return value if isinstance(value, dict) else {}


def _safe(value: Any) -> Any:
    def bounded(item: Any, depth: int = 0) -> Any:
        if depth > 5:
            return "[truncated]"
        if isinstance(item, dict):
            values = {str(key): bounded(value, depth + 1) for key, value in list(item.items())[:100]}
            if len(item) > 100:
                values["_truncated"] = True
            return values
        if isinstance(item, list):
            values = [bounded(value, depth + 1) for value in item[:100]]
            if len(item) > 100:
                values.append("[truncated]")
            return values
        if isinstance(item, str) and len(item) > 4000:
            return item[:4000] + "...[truncated]"
        return item

    return json.loads(json.dumps(bounded(value), ensure_ascii=False, default=str))


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Supervisor:
    """A persisted, bounded state machine wrapped in a LangGraph loop."""

    def __init__(self, context: SupervisorContext):
        self.context = context
        self.graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(AgentGraphState)
        graph.add_node("supervisor_step", self._step)
        graph.set_entry_point("supervisor_step")
        graph.add_conditional_edges("supervisor_step", self._next, {"continue": "supervisor_step", "end": END})
        return graph.compile()

    def _run_row(self) -> Any:
        return self.context.session.execute(
            text("SELECT * FROM agent_run WHERE run_id=:run_id"), {"run_id": self.context.run_id}
        ).mappings().one_or_none()

    def _state(self) -> AgentGraphState:
        row = self._run_row()
        if row is None:
            raise AppError("AGENT_RUN_NOT_FOUND", "Agent 运行不存在", status_code=404)
        return _decode(row["state_snapshot"])

    def _persist(self, state: AgentGraphState) -> None:
        state["state_version"] = int(state.get("state_version", 1)) + 1
        self.context.session.execute(
            text("""UPDATE agent_run SET state_snapshot=:state_snapshot,
                updated_at=:updated_at WHERE run_id=:run_id"""),
            {
                "state_snapshot": json.dumps(_safe(state), ensure_ascii=False, default=str),
                "updated_at": _now(),
                "run_id": self.context.run_id,
            },
        )
        self.context.session.commit()

    def _transition(
        self,
        state: AgentGraphState,
        *,
        status: str,
        stage: str,
        stop_reason: str | None = None,
        confirmation_status: str = "NOT_REQUIRED",
    ) -> AgentGraphState:
        state["status"] = status  # type: ignore[typeddict-item]
        state["current_stage"] = stage
        state["stop_reason"] = stop_reason  # type: ignore[typeddict-item]
        state["confirmation_status"] = confirmation_status  # type: ignore[typeddict-item]
        self._persist(state)
        transition_agent_run(
            self.context.session,
            self.context.user,
            self.context.run_id,
            status=status,
            current_stage=stage,
            stop_reason=stop_reason,
            confirmation_status=confirmation_status,
        )
        return state

    def _next(self, state: AgentGraphState) -> str:
        if state.get("status") in TERMINAL or state.get("status") == "WAITING_CONFIRMATION":
            return "end"
        return "continue"

    def _limit_hit(self, state: AgentGraphState) -> AgentGraphState | None:
        elapsed = (datetime.now(UTC).replace(tzinfo=None) - self.context.started_at).total_seconds()
        if elapsed > self.context.limits.max_duration_seconds:
            return self._stop(state, "TIMEOUT", "Supervisor 达到总耗时限制", status="BLOCKED")
        if int(state.get("tool_call_count", 0)) >= self.context.limits.max_tool_calls:
            return self._stop(state, "TIMEOUT", "Supervisor 达到工具调用次数限制", status="BLOCKED")
        if int(state.get("model_call_count", 0)) >= self.context.limits.max_model_calls and state.get("current_stage") == "EXPLAIN":
            return self._stop(state, "MODEL_ERROR", "Supervisor 达到模型调用次数限制", status="FAILED")
        if int(state.get("iteration", 0)) >= self.context.limits.max_loop_iterations:
            return self._stop(state, "NO_PROGRESS", "Supervisor 达到循环次数限制", status="BLOCKED")
        return None

    def _cancelled(self) -> bool:
        row = self._run_row()
        return row is not None and row["status"] == "CANCELLED"

    def _progress_signature(self, state: AgentGraphState) -> str:
        return json.dumps(
            {
                "stage": state.get("current_stage"),
                "status": state.get("status"),
                "tool_count": state.get("tool_call_count"),
                "model_count": state.get("model_call_count"),
                "tool_names": sorted((state.get("tool_results") or {}).keys()),
                "conclusion": bool(state.get("conclusion")),
            },
            sort_keys=True,
        )

    def _error(self, state: AgentGraphState, code: str, message: str, *, retryable: bool = False, details: dict[str, Any] | None = None) -> None:
        errors = state.setdefault("errors", [])
        errors.append(AgentError(code=code, message=message, retryable=retryable, details=details or {}, occurred_at=_now()).model_dump(mode="json"))

    def _stop(self, state: AgentGraphState, reason: str, message: str, *, status: str = "BLOCKED") -> AgentGraphState:
        state["resume_stage"] = state.get("current_stage", "READ_BUSINESS_DATA")
        self._error(state, reason, message)
        return self._transition(state, status=status, stage="STOPPED", stop_reason=reason)

    def _tool(
        self,
        state: AgentGraphState,
        tool_name: str,
        params: dict[str, Any],
        *,
        required: bool = True,
        idempotency_key: str | None = None,
    ) -> dict[str, Any] | None:
        if self._cancelled():
            state["status"] = "CANCELLED"
            state["current_stage"] = "CANCELLED"
            self._persist(state)
            return None
        if tool_name in state.get("tool_results", {}):
            return state["tool_results"][tool_name]
        if int(state.get("tool_call_count", 0)) >= self.context.limits.max_tool_calls:
            self._stop(state, "TIMEOUT", "工具调用次数达到上限", status="BLOCKED")
            return None
        try:
            response = execute_tool(
                self.context.session,
                self.context.settings,
                self.context.user,
                self.context.run_id,
                tool_name,
                params,
                idempotency_key,
            )
            if response.status != "SUCCEEDED":
                error = response.error or {"error_code": "TOOL_EXECUTION_FAILED", "message": "工具返回失败状态", "retryable": False}
                raise AppError(
                    "AGENT_TOOL_EXECUTION_FAILED",
                    str(error.get("message") or "工具返回失败状态"),
                    status_code=502 if error.get("retryable") else 400,
                    retryable=bool(error.get("retryable")),
                    details=error,
                )
        except AppError as exc:
            state["tool_call_count"] = int(state.get("tool_call_count", 0)) + 1
            details = exc.details if isinstance(exc.details, dict) else {}
            code = str(details.get("error_code") or exc.error_code)
            retries = state.setdefault("retry_counts", {})
            count = int(retries.get(tool_name, 0))
            if exc.retryable and count < 1:
                retries[tool_name] = count + 1
                self._error(state, code, exc.message, retryable=True, details=details)
                self._persist(state)
                return None
            self._error(state, code, exc.message, retryable=exc.retryable, details=details)
            self._transition(
                state,
                status="FAILED" if not required or not exc.retryable else "BLOCKED",
                stage="STOPPED",
                stop_reason="TOOL_ERROR",
            )
            return None
        state["tool_call_count"] = int(state.get("tool_call_count", 0)) + 1
        retries = state.setdefault("retry_counts", {})
        retries[tool_name] = 0
        result = response.result
        state.setdefault("tool_results", {})[tool_name] = result
        self._persist(state)
        if self._cancelled():
            state["status"] = "CANCELLED"
            state["current_stage"] = "CANCELLED"
            return None
        if (datetime.now(UTC).replace(tzinfo=None) - self.context.started_at).total_seconds() > self.context.limits.max_duration_seconds:
            self._stop(state, "TIMEOUT", "工具调用后达到 Supervisor 总耗时限制", status="BLOCKED")
            return None
        return result

    def _business_specs(self, state: AgentGraphState) -> list[tuple[str, dict[str, Any], bool]]:
        payload = state.get("user_input", {})
        version = state.get("data_version")
        base = {"data_version": version} if version else {}
        agent_type = state.get("agent_type")
        if agent_type == "coverage_gap":
            region = payload.get("region_code")
            station = {**base, "region_code": region, "page": 1, "page_size": 200, "all_pages": True, "max_rows": 50000}
            return [
                ("region.query", {**base, "region_code": region, "page": 1, "page_size": 10, "include_boundary": True}, True),
                ("station.query", station, True),
            ]
        if agent_type == "competition":
            station = {
                **base,
                "latitude": payload.get("latitude"),
                "longitude": payload.get("longitude"),
                "radius_km": payload.get("radius_km", 5),
                "page": 1,
                "page_size": 200,
                "all_pages": True,
                "max_rows": 50000,
            }
            return [("station.query", station, True)]
        if agent_type == "site_selection":
            return [("candidate.query", {**base, "candidate_ids": payload.get("candidate_site_ids", []), "page": 1, "page_size": 100}, True)]
        if agent_type == "expansion":
            start_date = payload.get("start_date")
            end_date = payload.get("end_date")
            return [
                ("station.query", {**base, "page": 1, "page_size": 200}, True),
                ("operation.query", {**base, "start_date": start_date, "end_date": end_date, "page": 1, "page_size": 500}, False),
                ("fault.query", {**base, "page": 1, "page_size": 500, "started_from": f"{start_date}T00:00:00" if start_date else None, "started_to": f"{end_date}T23:59:59" if end_date else None}, False),
            ]
        if agent_type == "policy_matching":
            return [("policy.query", {**base, "region_code": payload.get("region_code"), "page": 1, "page_size": 100}, True)]
        raise AppError("AGENT_TYPE_UNSUPPORTED", "不支持的 Agent 类型", status_code=400)

    def _read_business(self, state: AgentGraphState) -> AgentGraphState:
        for tool_name, params, required in self._business_specs(state):
            result = self._tool(state, tool_name, params, required=required)
            if result is None:
                return state
            payload = state.get("user_input", {})
            if state.get("agent_type") == "site_selection" and tool_name == "candidate.query":
                wanted = {int(value) for value in payload.get("candidate_site_ids", [])}
                result["items"] = [item for item in result.get("items", []) if int(item.get("id", -1)) in wanted]
            if state.get("agent_type") == "expansion":
                wanted = {int(value) for value in payload.get("station_ids", [])}
                if tool_name == "station.query":
                    result["items"] = [item for item in result.get("items", []) if int(item.get("id", -1)) in wanted]
                elif tool_name in {"operation.query", "fault.query"}:
                    result["items"] = [item for item in result.get("items", []) if int(item.get("station_id", -1)) in wanted]
            if required and not result.get("items"):
                return self._stop(state, "MISSING_BUSINESS_DATA", f"工具 {tool_name} 没有返回业务数据")
            if state.get("agent_type") == "coverage_gap" and tool_name == "region.query":
                region_items = result.get("items", [])
                if not region_items:
                    return self._stop(state, "MISSING_BUSINESS_DATA", "目标区域不存在")
                if not region_items[0].get("boundary_geojson"):
                    return self._stop(state, "MISSING_BUSINESS_DATA", "目标区域缺少有效边界，无法计算空间覆盖")
        if state.get("agent_type") == "coverage_gap":
            region_result = state.get("tool_results", {}).get("region.query", {})
            region_items = region_result.get("items", []) if isinstance(region_result, dict) else []
            region = region_items[0] if region_items else None
            if not region:
                return self._stop(state, "MISSING_BUSINESS_DATA", "目标区域不存在")
            if not region.get("boundary_geojson"):
                return self._stop(state, "MISSING_BUSINESS_DATA", "目标区域缺少有效边界，无法计算空间覆盖")
            station_items = state.get("tool_results", {}).get("station.query", {}).get("items", [])
            station_ids = [int(item["id"]) for item in station_items if item.get("id") is not None]
            connector_result = self._tool(
                state,
                "connector.query",
                {**(state.get("data_version") and {"data_version": state.get("data_version")} or {}), "station_ids": station_ids, "page": 1, "page_size": 500, "all_pages": True, "max_rows": 100000},
                required=False,
            )
            if connector_result is None:
                return state
            operation_result = self._tool(
                state,
                "operation.query",
                {**(state.get("data_version") and {"data_version": state.get("data_version")} or {}), "station_ids": station_ids, "page": 1, "page_size": 500, "all_pages": True, "max_rows": 100000},
                required=False,
            )
            if operation_result is None:
                return state
        if state.get("agent_type") == "competition":
            station_items = state.get("tool_results", {}).get("station.query", {}).get("items", [])
            station_ids = [int(item["id"]) for item in station_items if item.get("id") is not None]
            connector_result = self._tool(
                state,
                "connector.query",
                {**(state.get("data_version") and {"data_version": state.get("data_version")} or {}), "station_ids": station_ids, "page": 1, "page_size": 500, "all_pages": True, "max_rows": 100000},
                required=False,
            )
            if connector_result is None:
                return state
        if state.get("agent_type") == "site_selection":
            candidate_items = state.get("tool_results", {}).get("candidate.query", {}).get("items", [])
            region_result = self._tool(
                state,
                "region.query",
                {**(state.get("data_version") and {"data_version": state.get("data_version")} or {}), "page": 1, "page_size": 200},
                required=False,
            )
            if region_result is None:
                return state
            points = [
                (float(item["latitude"]), float(item["longitude"]))
                for item in candidate_items
                if item.get("latitude") is not None and item.get("longitude") is not None
            ]
            if points:
                radius = float(state.get("user_input", {}).get("nearby_radius_km", 5.0))
                lat_delta = radius / 111.0
                min_lat = min(point[0] for point in points) - lat_delta
                max_lat = max(point[0] for point in points) + lat_delta
                min_lon = min(point[1] for point in points) - max(lat_delta, 0.1)
                max_lon = max(point[1] for point in points) + max(lat_delta, 0.1)
                station_result = self._tool(
                    state,
                    "station.query",
                    {
                        **(state.get("data_version") and {"data_version": state.get("data_version")} or {}),
                        "min_latitude": max(-90.0, min_lat),
                        "max_latitude": min(90.0, max_lat),
                        "min_longitude": max(-180.0, min_lon),
                        "max_longitude": min(180.0, max_lon),
                        "page": 1,
                        "page_size": 200,
                        "all_pages": True,
                        "max_rows": 50000,
                    },
                    required=False,
                )
                if station_result is None:
                    return state
            else:
                state.setdefault("tool_results", {})["station.query"] = {"items": [], "page": {"total": 0}}
                self._persist(state)
        state["current_stage"] = "RETRIEVE_EVIDENCE"
        self._persist(state)
        return state

    def _rag_query(self, state: AgentGraphState) -> dict[str, Any]:
        payload = state.get("user_input", {})
        region = payload.get("region_code") or (state.get("business_scope") or {}).get("region_code")
        agent_type = state.get("agent_type")
        queries = {
            "coverage_gap": f"{region or ''} 充电站覆盖率 快充 建设标准",
            "competition": f"{payload.get('latitude')} {payload.get('longitude')} 充电站竞争 运营商服务要求",
            "site_selection": "充电站候选选址建设审批条件",
            "expansion": "充电站扩容建设 容量 利用率 故障标准",
            "policy_matching": f"{region or ''} 充电站建设补贴政策 资格 申请材料",
        }
        return {
            "query": queries.get(agent_type, "充电站建设规则"),
            "top_k": 5,
            # Existing public documents may predate scenario labels.  The
            # business Agent still records its scenario in the run state, but
            # retrieval must not discard otherwise valid evidence.
            "agent_scenario": None,
            "region_code": region,
            "use_vector": True,
            "use_keyword": True,
            "use_rerank": False,
        }

    def _retrieve_evidence(self, state: AgentGraphState) -> AgentGraphState:
        result = self._tool(state, "rag.search", self._rag_query(state), required=True)
        if result is None:
            return state
        if result.get("status") in {"NO_HIT", "EVIDENCE_INSUFFICIENT"} or not result.get("hits"):
            return self._stop(state, "EVIDENCE_INSUFFICIENT", "RAG 没有返回足够的可回溯证据")
        verified = self._tool(
            state,
            "rag.evidence.verify",
            {"evidence": result.get("hits", [])},
            required=True,
        )
        if verified is None or not verified.get("valid_count"):
            return self._stop(state, "EVIDENCE_INSUFFICIENT", "RAG 证据未通过 Chunk 和原文位置校验")
        valid_ids = {item.get("chunk_id") for item in verified.get("valid", [])}
        result["hits"] = [item for item in result.get("hits", []) if item.get("chunk_id") in valid_ids]
        evidence = []
        for hit in result.get("hits", []):
            evidence.append(
                AgentEvidence(
                    evidence_id=str(hit.get("chunk_id")),
                    document_id=hit.get("document_id"),
                    chunk_id=hit.get("chunk_id"),
                    title=hit.get("title"),
                    content=str(hit.get("content") or ""),
                    source_url=hit.get("source_url"),
                    original_fragment=hit.get("original_fragment"),
                    original_href=hit.get("original_href"),
                    version=hit.get("version"),
                    start_char=hit.get("start_char"),
                    end_char=hit.get("end_char"),
                    score=hit.get("score"),
                ).model_dump(mode="json")
            )
        state["evidence"] = evidence
        state["current_stage"] = "CALCULATE"
        self._persist(state)
        return state

    def _calculation_params(self, state: AgentGraphState) -> tuple[str, dict[str, Any]]:
        payload = state.get("user_input", {})
        results = state.get("tool_results", {})
        agent_type = state.get("agent_type")
        if agent_type == "coverage_gap":
            items = results.get("station.query", {}).get("items", [])
            region_items = results.get("region.query", {}).get("items", [])
            return "coverage.analyze", {
                **payload,
                "region": region_items[0] if region_items else None,
                "stations": items,
                "connectors": results.get("connector.query", {}).get("items", []),
                "metrics": results.get("operation.query", {}).get("items", []),
            }
        if agent_type == "competition":
            items = results.get("station.query", {}).get("items", [])
            return "competition.analyze", {
                **payload,
                "nearby_stations": items,
                "connectors": results.get("connector.query", {}).get("items", []),
            }
        if agent_type == "site_selection":
            items = results.get("candidate.query", {}).get("items", [])
            return "site.score", {
                **payload,
                "candidates": items,
                "regions": results.get("region.query", {}).get("items", []),
                "stations": results.get("station.query", {}).get("items", []),
                "weights": payload.get("weights", {}),
            }
        if agent_type == "expansion":
            items = results.get("station.query", {}).get("items", [])
            return "expansion.plan", {"stations": items, "budget_usd": payload.get("budget_usd")}
        policies = results.get("policy.query", {}).get("items", [])
        subject = {
            "region_code": payload.get("region_code"),
            "subject_type": payload.get("subject_type"),
            "planned_scale_kw": payload.get("planned_scale_kw"),
            "planned_date": payload.get("planned_date"),
        }
        return "policy.match", {"policies": policies, "subject": subject}

    def _calculate(self, state: AgentGraphState) -> AgentGraphState:
        tool_name, params = self._calculation_params(state)
        result = self._tool(state, tool_name, params, required=True)
        if result is None:
            return state
        state.setdefault("calculation_results", {})[tool_name] = result
        if result.get("status") != "COMPLETED":
            reason = result.get("stop_reason") or result.get("status") or "MISSING_BUSINESS_DATA"
            labels = {
                "coverage_gap": "覆盖缺口分析",
                "competition": "竞争分析",
                "site_selection": "候选选址评分",
                "expansion": "站点扩容规划",
                "policy_matching": "政策匹配",
            }
            return self._stop(state, str(reason), str(result.get("conclusion") or f"{labels.get(state.get('agent_type'), 'Agent')}无法完成"), status="BLOCKED")
        if tool_name == "site.score" and not result.get("ranked_candidates"):
            return self._stop(state, "MISSING_BUSINESS_DATA", "没有可评分的候选站点")
        if tool_name == "expansion.plan" and not result.get("plans"):
            return self._stop(state, "MISSING_BUSINESS_DATA", "没有可生成扩容方案的站点")
        state["current_stage"] = "EXPLAIN"
        self._persist(state)
        return state

    def _explanation(self, state: AgentGraphState) -> str:
        result = next(iter(state.get("calculation_results", {}).values()), {})
        agent_type = state.get("agent_type")
        if agent_type == "coverage_gap":
            metrics = result.get("metrics", {})
            return (
                f"覆盖得分 {result.get('coverage_score', 0):.3f}，站点密度 {metrics.get('station_density_per_sq_km', 0)} 个/平方公里，"
                f"最近站点距离 {result.get('nearest_station_distance_km', 0)} 公里，识别缺口：{', '.join(result.get('gap_types', [])) or '无'}。"
            )
        if agent_type == "competition":
            concentration = result.get("operator_concentration", {})
            return (
                f"周边站点 {result.get('nearby_station_count', 0)} 个，竞争指数 {result.get('competition_index', 0):.2f}，"
                f"运营商集中度 HHI {concentration.get('hhi', 0):.4f}，服务空白：{', '.join(result.get('service_gaps', [])) or '无'}。"
            )
        if agent_type == "site_selection":
            ranked = result.get("ranked_candidates", [])
            selected = ranked[0] if ranked else {}
            return (
                f"已完成 {len(ranked)} 个候选站点评分，首选候选站点为 {result.get('selected_candidate_id')}，"
                f"总分 {selected.get('total_score', 0):.2f}，等级 {selected.get('recommendation_grade', 'C')}，"
                f"数据可信度 {selected.get('data_confidence_score', 0):.2f}。"
            )
        if agent_type == "expansion":
            return f"已生成 {len(result.get('plans', []))} 个扩容方案，发布前需要人工确认。"
        return f"已匹配 {len(result.get('matched_policies', []))} 条政策，缺失条件 {len(result.get('missing_conditions', []))} 项。"

    def _explain(self, state: AgentGraphState) -> AgentGraphState:
        if state.get("conclusion"):
            state["current_stage"] = "SAVE"
            self._persist(state)
            return state
        if int(state.get("model_call_count", 0)) >= self.context.limits.max_model_calls:
            return self._stop(state, "MODEL_ERROR", "没有剩余模型调用额度", status="FAILED")
        started = time.perf_counter()
        conclusion = self._explanation(state)
        record_agent_event(
            self.context.session,
            ModelCallRecord(
                run_id=self.context.run_id,
                sequence_no=0,
                provider="deterministic-supervisor",
                model_name=state.get("model_name") or self.context.settings.llm_model or "supervisor-rule-v1",
                prompt_version=state.get("prompt_version"),
                input_summary={
                    "agent_type": state.get("agent_type"),
                    "stage": "EXPLAIN",
                    "system_prompt": (
                        COVERAGE_GAP_SYSTEM_PROMPT if state.get("agent_type") == "coverage_gap"
                        else COMPETITION_SYSTEM_PROMPT if state.get("agent_type") == "competition"
                        else SITE_SELECTION_SYSTEM_PROMPT if state.get("agent_type") == "site_selection"
                        else "supervisor-rule-v1"
                    ),
                },
                output_summary={"conclusion": conclusion},
                status="SUCCEEDED",
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
            ),
            event_type="MODEL_CALL",
            status="SUCCEEDED",
            actor_user_id=self.context.user.user_id,
        )
        state["model_call_count"] = int(state.get("model_call_count", 0)) + 1
        state["conclusion"] = {"status": "WAITING_CONFIRMATION" if state.get("agent_type") == "expansion" else "COMPLETED", "conclusion": conclusion, "evidence": state.get("evidence", []), "data_version": state.get("data_version")}
        if state.get("agent_type") == "expansion":
            state["confirmation_status"] = "PENDING"
            state["status"] = "WAITING_CONFIRMATION"
            state["current_stage"] = "WAITING_CONFIRMATION"
            self._persist(state)
            transition_agent_run(
                self.context.session,
                self.context.user,
                self.context.run_id,
                status="WAITING_CONFIRMATION",
                current_stage="WAITING_CONFIRMATION",
                stop_reason="WAITING_CONFIRMATION",
                confirmation_status="PENDING",
            )
            return state
        state["current_stage"] = "SAVE"
        self._persist(state)
        return state

    def _save(self, state: AgentGraphState) -> AgentGraphState:
        agent_type = state.get("agent_type")
        calc = next(iter(state.get("calculation_results", {}).values()), {})
        conclusion = state.get("conclusion") or {}
        version = state.get("data_version")
        if agent_type == "expansion":
            plan = (calc.get("plans") or [{}])[0]
            params = {"station_id": plan.get("station_id"), "plan": plan, "data_version": version, "evidence": state.get("evidence", [])}
            result = self._tool(state, "expansion.result.write", params, required=True, idempotency_key=f"{self.context.run_id}:expansion")
        elif agent_type == "site_selection":
            selected = (calc.get("ranked_candidates") or [{}])[0]
            params = {
                "candidate_site_id": selected.get("candidate_site_id"),
                "result": {**selected, "status": "DRAFT", "evidence": state.get("evidence", [])},
                "scoring_rule_version": calc.get("scoring_rule_version") or calc.get("scoring_breakdown", {}).get("rule_version", "site-selection-score-v1"),
                "data_version": version,
            }
            result = self._tool(state, "score.result.write", params, required=True, idempotency_key=f"{self.context.run_id}:score")
        else:
            output = {**calc, "status": "COMPLETED", "conclusion": conclusion.get("conclusion"), "evidence": state.get("evidence", []), "data_version": version}
            result = self._tool(state, "analysis.result.write", {"result": output, "data_version": version}, required=True, idempotency_key=f"{self.context.run_id}:analysis")
        if result is None:
            return state
        return self._transition(state, status="COMPLETED", stage="COMPLETED", confirmation_status="NOT_REQUIRED")

    def _step(self, state: AgentGraphState) -> AgentGraphState:
        if self._cancelled():
            state["status"] = "CANCELLED"
            state["current_stage"] = "CANCELLED"
            self._persist(state)
            return state
        state["iteration"] = int(state.get("iteration", 0)) + 1
        limit = self._limit_hit(state)
        if limit is not None:
            return limit
        stage = state.get("current_stage", "READ_BUSINESS_DATA")
        if stage in {"CREATED", "ROUTING"}:
            stage = "READ_BUSINESS_DATA"
            state["current_stage"] = stage
        before = self._progress_signature(state)
        if stage == "READ_BUSINESS_DATA":
            result = self._read_business(state)
        elif stage == "RETRIEVE_EVIDENCE":
            result = self._retrieve_evidence(state)
        elif stage == "CALCULATE":
            result = self._calculate(state)
        elif stage == "EXPLAIN":
            result = self._explain(state)
        elif stage == "SAVE":
            result = self._save(state)
        else:
            result = self._stop(state, "NO_PROGRESS", f"无法识别的 Supervisor 阶段：{stage}")
        if result.get("status") not in TERMINAL and result.get("status") != "WAITING_CONFIRMATION":
            after = self._progress_signature(result)
            streak = int(result.get("no_progress_streak", 0)) + 1 if before == after else 0
            result["progress_signature"] = after
            result["no_progress_streak"] = streak
            self._persist(result)
            if streak >= 2:
                return self._stop(result, "NO_PROGRESS", "Supervisor 连续两轮没有状态进展")
        return result

    def run(self) -> Any:
        row = self._run_row()
        if row is None:
            raise AppError("AGENT_RUN_NOT_FOUND", "Agent 运行不存在", status_code=404)
        if row["status"] in TERMINAL or row["status"] == "WAITING_CONFIRMATION":
            return get_agent_run(self.context.session, self.context.run_id)
        state = self._state()
        if row["status"] == "PENDING":
            state["status"] = "RUNNING"
            state["current_stage"] = "READ_BUSINESS_DATA"
            self._persist(state)
            transition_agent_run(
                self.context.session,
                self.context.user,
                self.context.run_id,
                status="RUNNING",
                current_stage="READ_BUSINESS_DATA",
            )
            state = self._state()
        try:
            self.graph.invoke(state, config={"recursion_limit": self.context.limits.max_loop_iterations + 3})
        except GraphRecursionError:
            state = self._state()
            if state.get("status") not in TERMINAL and state.get("status") != "WAITING_CONFIRMATION":
                self._stop(state, "NO_PROGRESS", "LangGraph 循环达到递归限制")
        except Exception as exc:
            state = self._state()
            if state.get("status") not in TERMINAL and state.get("status") != "WAITING_CONFIRMATION":
                self._error(state, "MODEL_ERROR", str(exc))
                self._transition(state, status="FAILED", stage="STOPPED", stop_reason="MODEL_ERROR")
        return get_agent_run(self.context.session, self.context.run_id)


def run_supervisor(
    session: Session,
    settings: Settings,
    user: UserContext,
    run_id: str,
    request: SupervisorExecuteRequest | None = None,
) -> Any:
    row = session.execute(text("SELECT started_at FROM agent_run WHERE run_id=:run_id"), {"run_id": run_id}).mappings().one_or_none()
    started_at = row["started_at"] if row and row["started_at"] else datetime.now(UTC).replace(tzinfo=None)
    context = SupervisorContext(
        session=session,
        settings=settings,
        user=user,
        run_id=run_id,
        limits=SupervisorLimits.from_request(request),
        started_at=started_at,
    )
    return Supervisor(context).run()


def confirm_agent_run(
    session: Session,
    settings: Settings,
    user: UserContext,
    run_id: str,
    *,
    decision: str,
    comment: str,
    request: SupervisorExecuteRequest | None = None,
) -> Any:
    detail = get_agent_run(session, run_id)
    if detail is None:
        raise AppError("AGENT_RUN_NOT_FOUND", "Agent 运行不存在", status_code=404)
    if detail.status != "WAITING_CONFIRMATION":
        raise AppError("CONFIRMATION_NOT_PENDING", "当前 Agent 运行不在等待确认状态", status_code=409, details={"status": detail.status})
    require_high_risk_confirmation(user, "expansion_publish", session=session)
    status = "APPROVED" if decision == "APPROVE" else "REJECTED"
    record_agent_event(
        session,
        ConfirmationRecord(
            run_id=run_id,
            confirmation_type="expansion_publish",
            status=status,  # type: ignore[arg-type]
            requested_by=detail.requested_by,
            decided_by=user.user_id,
            comment=comment,
            requested_at=detail.created_at,
            decided_at=_now(),
        ),
        event_type="HUMAN_CONFIRMATION",
        status=status,
        actor_user_id=user.user_id,
    )
    row = session.execute(text("SELECT state_snapshot FROM agent_run WHERE run_id=:run_id"), {"run_id": run_id}).mappings().one()
    state: AgentGraphState = _decode(row["state_snapshot"])
    if decision == "REJECT":
        state["resume_stage"] = "READ_BUSINESS_DATA"
        state["confirmation_status"] = "REJECTED"
        state["status"] = "FAILED"
        state["current_stage"] = "STOPPED"
        state["stop_reason"] = "WAITING_CONFIRMATION"
        Supervisor(
            SupervisorContext(session, settings, user, run_id, SupervisorLimits.from_request(request), datetime.now(UTC).replace(tzinfo=None))
        )._persist(state)
        transition_agent_run(
            session,
            user,
            run_id,
            status="FAILED",
            current_stage="STOPPED",
            stop_reason="WAITING_CONFIRMATION",
            confirmation_status="REJECTED",
        )
        return get_agent_run(session, run_id)
    transition_agent_run(
        session,
        user,
        run_id,
        status="RUNNING",
        current_stage="SAVE",
        confirmation_status="APPROVED",
        state_patch={"confirmation_status": "APPROVED", "current_stage": "SAVE", "stop_reason": None},
    )
    return run_supervisor(session, settings, user, run_id, request)


def retry_agent_run(
    session: Session,
    settings: Settings,
    user: UserContext,
    run_id: str,
    request: SupervisorExecuteRequest | None = None,
) -> Any:
    detail = get_agent_run(session, run_id)
    if detail is None:
        raise AppError("AGENT_RUN_NOT_FOUND", "Agent 运行不存在", status_code=404)
    if detail.status not in {"FAILED", "BLOCKED"}:
        raise AppError("AGENT_RETRY_NOT_ALLOWED", "只有失败或阻塞的 Agent 运行可以重试", status_code=409, details={"status": detail.status})
    stage = detail.state_snapshot.get("resume_stage", "READ_BUSINESS_DATA")
    transition_agent_run(
        session,
        user,
        run_id,
        status="RUNNING",
        current_stage=stage,
        confirmation_status="NOT_REQUIRED",
        state_patch={"status": "RUNNING", "current_stage": stage, "stop_reason": None, "confirmation_status": "NOT_REQUIRED"},
    )
    return run_supervisor(session, settings, user, run_id, request)


def cancel_agent_run(session: Session, user: UserContext, run_id: str) -> Any:
    detail = get_agent_run(session, run_id)
    if detail is None:
        raise AppError("AGENT_RUN_NOT_FOUND", "Agent 运行不存在", status_code=404)
    if detail.status in TERMINAL:
        raise AppError("AGENT_CANCEL_NOT_ALLOWED", "当前 Agent 运行已经结束", status_code=409, details={"status": detail.status})
    return transition_agent_run(
        session,
        user,
        run_id,
        status="CANCELLED",
        current_stage="CANCELLED",
        stop_reason="CANCELLED",
        confirmation_status="REJECTED" if detail.status == "WAITING_CONFIRMATION" else "NOT_REQUIRED",
    )
