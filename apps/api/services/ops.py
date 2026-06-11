from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import Request, Response, UploadFile
from fastapi.responses import JSONResponse

from apps.api.common import (
    auth,
    case_learning_repository,
    case_repository,
    ensure_artifact_ref,
    get_case,
    media_repository,
    object_store,
    ops_repository,
    page,
    production_repository,
    prompt_repository,
    provider_repository,
    publishing_repository,
    repository,
    request_id,
    secret_repository,
    secret_store,
    signed,
    upload_repository,
    workflow_runtime,
)
from apps.api.dependencies import SESSION_COOKIE, current_user, not_found_response
from packages.core import contracts as c
from packages.core.auth import SqlAlchemyAuthService
from packages.core.contracts.state_machines import assert_transition
from packages.core.observability import metric_snapshot
from packages.core.registration_codes import hash_registration_code
from packages.core.storage.object_store import parse_local_uri
from packages.core.storage.repository import new_id
from packages.core.workflow import NodeExecutionError
from apps.api.services import providers as provider_service

def ops_dashboard(
    request: Request,
    window_start: datetime | None = None, window_end: datetime | None = None
) -> c.OpsDashboardVm:
    if ops_repository(request) is not None:
        return ops_repository(request).dashboard(window_start=window_start, window_end=window_end)
    usage = provider_service.provider_usage(request, window_start=window_start, window_end=window_end)
    funnel = yield_funnel(request, window_start=window_start, window_end=window_end)
    return c.OpsDashboardVm(
        usage=usage,
        yield_funnel=funnel,
        alerts=list(repository(request).alerts.values()),
        cost_rollups=list(repository(request).cost_rollups.values()),
    )


def cost_rollups(
    request: Request,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    group_by: str | None = None,
    limit: int = 50,
) -> c.PageResponse[c.CostRollup]:
    if ops_repository(request) is not None:
        values = ops_repository(request).list_cost_rollups(
            window_start=window_start,
            window_end=window_end,
            group_by=group_by,
            limit=limit,
        )
        return c.PageResponse(items=values, total_hint=len(values), request_id=request_id())
    rollup = c.CostRollup(
        id="cost_current",
        group_key=group_by or "all",
        group_by=group_by,
        estimated_cost=c.Money(
            amount=sum(
                (item.estimated_cost.amount for item in repository(request).provider_invocations.values() if item.estimated_cost),
                c.Decimal("0"),
            ),
            currency="CNY",
        ),
        invocations=len(repository(request).provider_invocations),
    )
    repository(request).cost_rollups[rollup.id] = rollup
    return page(repository(request).cost_rollups.values(), limit)


def yield_funnel(
    request: Request,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    case_id: str | None = None,
) -> c.YieldFunnelResponse:
    if ops_repository(request) is not None:
        return ops_repository(request).yield_funnel(
            window_start=window_start,
            window_end=window_end,
            case_id=case_id,
        )
    events = [
        c.YieldFunnelEvent(
            id=f"yield_{run.id}",
            case_id=run.case_id,
            run_id=run.id,
            event_name=f"workflow_{run.status.value}",
            affects_true_yield=True,
        )
        for run in repository(request).runs.values()
        if case_id is None or run.case_id == case_id
    ]
    success = len([event for event in events if event.event_name == "workflow_succeeded"])
    rate = success / len(events) if events else None
    return c.YieldFunnelResponse(events=events, true_yield_rate=rate)


def budgets(request: Request, limit: int = 50) -> c.PageResponse[c.Budget]:

    if ops_repository(request) is not None:
        values = ops_repository(request).list_budgets(limit=limit)
        return c.PageResponse(items=values, total_hint=len(values), request_id=request_id())
    return page(repository(request).budgets.values(), limit)


def upsert_budget(payload: c.UpsertBudgetRequest, request: Request) -> c.Budget:
    if ops_repository(request) is not None:
        return ops_repository(request).upsert_budget(payload)
    repository(request).budgets[payload.budget.id] = payload.budget
    return payload.budget


def patch_budget(budget_id: str, payload: c.PatchBudgetRequest, request: Request) -> c.Budget:
    if ops_repository(request) is not None:
        return ops_repository(request).patch_budget(budget_id, payload)
    return repository(request).patch(repository(request).budgets, budget_id, payload.model_dump(exclude_none=True))


def ack_alert(event_id: str, payload: c.AcknowledgeAlertRequest, request: Request) -> c.OpsAlertEvent:
    if ops_repository(request) is not None:
        return ops_repository(request).patch_alert_status(event_id, "acknowledged")
    return repository(request).patch(repository(request).alerts, event_id, {"status": "acknowledged"})


def resolve_alert(event_id: str, payload: c.ResolveAlertRequest, request: Request) -> c.OpsAlertEvent:
    if ops_repository(request) is not None:
        return ops_repository(request).patch_alert_status(event_id, "resolved")
    return repository(request).patch(repository(request).alerts, event_id, {"status": "resolved"})


def run_quality_check(
    run_id: str, payload: c.CreateQualityCheckRequest, request: Request
) -> c.ProductionQualityCheck:
    if ops_repository(request) is not None:
        return ops_repository(request).create_quality_check(
            target_type="run",
            target_id=run_id,
            payload=payload,
        )
    check = c.ProductionQualityCheck(id=new_id("qc"), target_type="run", target_id=run_id, **payload.model_dump())
    repository(request).quality_checks[check.id] = check
    return check


def finished_video_quality_check(
    id: str, payload: c.CreateQualityCheckRequest, request: Request
) -> c.ProductionQualityCheck:
    if ops_repository(request) is not None:
        return ops_repository(request).create_quality_check(
            target_type="finished_video",
            target_id=id,
            payload=payload,
        )
    check = c.ProductionQualityCheck(
        id=new_id("qc"),
        target_type="finished_video",
        target_id=id,
        **payload.model_dump(),
    )
    repository(request).quality_checks[check.id] = check
    return check


def approve_request(id: str, payload: c.ApprovalDecisionRequest, request: Request) -> c.ApprovalRequest:
    if ops_repository(request) is not None:
        return ops_repository(request).decide_approval(id, "approved", payload)
    approval = c.ApprovalRequest(
        id=id,
        resource_type="unknown",
        resource_id=None,
        status="approved",
        reason=payload.reason,
    )
    repository(request).approvals[id] = approval
    return approval


def reject_request(id: str, payload: c.ApprovalDecisionRequest, request: Request) -> c.ApprovalRequest:
    if ops_repository(request) is not None:
        return ops_repository(request).decide_approval(id, "rejected", payload)
    approval = c.ApprovalRequest(
        id=id,
        resource_type="unknown",
        resource_id=None,
        status="rejected",
        reason=payload.reason,
    )
    repository(request).approvals[id] = approval
    return approval


def audit_events(request: Request, limit: int = 50) -> c.PageResponse[c.AuditEvent]:
    if ops_repository(request) is not None:
        values = ops_repository(request).list_audit_events(limit=limit)
        return c.PageResponse(items=values, total_hint=len(values), request_id=request_id())
    return page(repository(request).audit_events.values(), limit)
