from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.agents.registry import TOOL_CONTRACTS, contracts_for_agent, get_tool_contract
from app.api.routes.auth import get_current_user
from app.config import Settings, get_settings
from app.db import get_db
from app.errors import AppError
from app.schemas.agents import AgentConfirmationRequest, AgentContractListResponse, AgentRunCreateRequest, AgentRunDetail, AgentRunListResponse, AgentRunTransitionRequest, SupervisorExecuteRequest, ToolExecuteRequest, ToolExecuteResponse
from app.services.agent_runs import create_agent_run, get_agent_run, list_agent_runs, transition_agent_run
from app.services.auth import UserContext, require_permission
from app.agents.supervisor import cancel_agent_run, confirm_agent_run, retry_agent_run, run_supervisor
from app.tools.executor import execute_tool


router = APIRouter(tags=["agents"])


@router.get("/agents/contracts", response_model=AgentContractListResponse, summary="List registered Agent tool contracts")
def agent_contracts(agent_type: str | None = Query(default=None), user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> AgentContractListResponse:
    require_permission(user, "agent.run.read", session=session)
    if agent_type:
        if agent_type not in {"coverage_gap", "competition", "site_selection", "expansion", "policy_matching"}:
            raise AppError("AGENT_TYPE_UNSUPPORTED", "不支持的 Agent 类型", status_code=400)
        return AgentContractListResponse(items=contracts_for_agent(agent_type))  # type: ignore[arg-type]
    return AgentContractListResponse(items=list(TOOL_CONTRACTS))


@router.get("/agents/contracts/{tool_name}", response_model=dict, summary="Get one Agent tool contract")
def agent_contract(tool_name: str, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> dict[str, object]:
    require_permission(user, "agent.run.read", session=session)
    contract = get_tool_contract(tool_name)
    if contract is None:
        raise AppError("AGENT_TOOL_NOT_FOUND", "Agent 工具契约不存在", status_code=404, details={"tool_name": tool_name})
    return contract.model_dump(mode="json")


@router.post("/agent-runs", response_model=AgentRunDetail, status_code=201, summary="Create an Agent run state")
def create_run(request: AgentRunCreateRequest, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> AgentRunDetail:
    require_permission(user, "agent.run.start", session=session)
    return create_agent_run(session, user, request)


@router.get("/agent-runs", response_model=AgentRunListResponse, summary="List Agent runs")
def agent_runs(agent_type: str | None = Query(default=None), user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> AgentRunListResponse:
    require_permission(user, "agent.run.read", session=session)
    requested_by = None if {"SYSTEM_ADMIN", "AUDITOR"} & set(user.role_codes) else user.user_id
    return list_agent_runs(session, requested_by=requested_by, agent_type=agent_type)


@router.get("/agent-runs/{run_id}", response_model=AgentRunDetail, summary="Get Agent run state and trace")
def agent_run_detail(run_id: str, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> AgentRunDetail:
    require_permission(user, "agent.run.read", session=session)
    result = get_agent_run(session, run_id)
    if result is None:
        raise AppError("AGENT_RUN_NOT_FOUND", "Agent 运行不存在", status_code=404, details={"run_id": run_id})
    if result.requested_by != user.user_id and not ({"SYSTEM_ADMIN", "AUDITOR"} & set(user.role_codes)):
        raise AppError("FORBIDDEN", "无权查看该 Agent 运行", status_code=403)
    return result


@router.post("/agent-runs/{run_id}/transition", response_model=AgentRunDetail, summary="Transition Agent run state")
def transition_run(run_id: str, request: AgentRunTransitionRequest, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> AgentRunDetail:
    require_permission(user, "agent.run.start", session=session)
    existing = get_agent_run(session, run_id)
    if existing is None:
        raise AppError("AGENT_RUN_NOT_FOUND", "Agent 运行不存在", status_code=404, details={"run_id": run_id})
    if existing.requested_by != user.user_id and "SYSTEM_ADMIN" not in user.role_codes:
        raise AppError("FORBIDDEN", "无权更新该 Agent 运行", status_code=403)
    return transition_agent_run(session, user, run_id, status=request.status, current_stage=request.current_stage, stop_reason=request.stop_reason, confirmation_status=request.confirmation_status, state_patch=request.state_patch)


@router.post("/agent-runs/{run_id}/tools/{tool_name:path}", response_model=ToolExecuteResponse, summary="Execute a registered Agent tool")
def execute_agent_tool(run_id: str, tool_name: str, request: ToolExecuteRequest, settings: Settings = Depends(get_settings), user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> ToolExecuteResponse:
    require_permission(user, "agent.run.start", session=session)
    existing = get_agent_run(session, run_id)
    if existing is None:
        raise AppError("AGENT_RUN_NOT_FOUND", "Agent 运行不存在", status_code=404, details={"run_id": run_id})
    if existing.requested_by != user.user_id and "SYSTEM_ADMIN" not in user.role_codes:
        raise AppError("FORBIDDEN", "无权执行该 Agent 运行的工具", status_code=403)
    return execute_tool(session, settings, user, run_id, tool_name, request.params, request.idempotency_key)


@router.post("/agent-runs/{run_id}/execute", response_model=AgentRunDetail, summary="Run the Supervisor loop")
def execute_agent_run(run_id: str, request: SupervisorExecuteRequest | None = None, settings: Settings = Depends(get_settings), user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> AgentRunDetail:
    require_permission(user, "agent.run.start", session=session)
    existing = get_agent_run(session, run_id)
    if existing is None:
        raise AppError("AGENT_RUN_NOT_FOUND", "Agent 运行不存在", status_code=404, details={"run_id": run_id})
    if existing.requested_by != user.user_id and "SYSTEM_ADMIN" not in user.role_codes:
        raise AppError("FORBIDDEN", "无权执行该 Agent 运行", status_code=403)
    return run_supervisor(session, settings, user, run_id, request)


@router.post("/agent-runs/{run_id}/confirmation", response_model=AgentRunDetail, summary="Approve or reject a waiting Agent result")
def confirm_agent_run_endpoint(run_id: str, request: AgentConfirmationRequest, settings: Settings = Depends(get_settings), user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> AgentRunDetail:
    require_permission(user, "agent.run.start", session=session)
    existing = get_agent_run(session, run_id)
    if existing is None:
        raise AppError("AGENT_RUN_NOT_FOUND", "Agent 运行不存在", status_code=404, details={"run_id": run_id})
    if existing.requested_by != user.user_id and "SYSTEM_ADMIN" not in user.role_codes:
        raise AppError("FORBIDDEN", "无权确认该 Agent 运行", status_code=403)
    return confirm_agent_run(session, settings, user, run_id, decision=request.decision, comment=request.comment)


@router.post("/agent-runs/{run_id}/retry", response_model=AgentRunDetail, summary="Retry a failed or blocked Agent run")
def retry_agent_run_endpoint(run_id: str, request: SupervisorExecuteRequest | None = None, settings: Settings = Depends(get_settings), user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> AgentRunDetail:
    require_permission(user, "agent.run.start", session=session)
    existing = get_agent_run(session, run_id)
    if existing is None:
        raise AppError("AGENT_RUN_NOT_FOUND", "Agent 运行不存在", status_code=404, details={"run_id": run_id})
    if existing.requested_by != user.user_id and "SYSTEM_ADMIN" not in user.role_codes:
        raise AppError("FORBIDDEN", "无权重试该 Agent 运行", status_code=403)
    return retry_agent_run(session, settings, user, run_id, request)


@router.post("/agent-runs/{run_id}/cancel", response_model=AgentRunDetail, summary="Cancel an Agent run")
def cancel_agent_run_endpoint(run_id: str, user: UserContext = Depends(get_current_user), session: Session = Depends(get_db)) -> AgentRunDetail:
    require_permission(user, "agent.run.start", session=session)
    existing = get_agent_run(session, run_id)
    if existing is None:
        raise AppError("AGENT_RUN_NOT_FOUND", "Agent 运行不存在", status_code=404, details={"run_id": run_id})
    if existing.requested_by != user.user_id and "SYSTEM_ADMIN" not in user.role_codes:
        raise AppError("FORBIDDEN", "无权取消该 Agent 运行", status_code=403)
    return cancel_agent_run(session, user, run_id)
