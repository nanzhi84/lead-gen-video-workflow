from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request

from apps.api.dependencies import require_role
from apps.api.services import ops as service
from packages.core import contracts as c

router = APIRouter()

@router.get("/api/ops/dashboard", response_model=c.OpsDashboardVm)
def ops_dashboard(
    request: Request,
    window_start: datetime | None = None, window_end: datetime | None = None
) -> c.OpsDashboardVm:
    return service.ops_dashboard(request, window_start, window_end)


@router.get("/api/ops/cost-rollups", response_model=c.PageResponse[c.CostRollup])
def cost_rollups(
    request: Request,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    group_by: str | None = None,
    limit: int = 50,
) -> c.PageResponse[c.CostRollup]:
    return service.cost_rollups(request, window_start, window_end, group_by, limit)


@router.get("/api/ops/yield-funnel", response_model=c.YieldFunnelResponse)
def yield_funnel(
    request: Request,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    case_id: str | None = None,
) -> c.YieldFunnelResponse:
    return service.yield_funnel(request, window_start, window_end, case_id)


@router.get("/api/ops/cost-metrics", response_model=c.CostMetrics)
def cost_metrics(
    request: Request,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> c.CostMetrics:
    require_role(request, c.UserRole.operator)
    return service.cost_metrics(request, window_start, window_end)


@router.get("/api/ops/provider-usage-metrics", response_model=c.ProviderUsageMetricsReport)
def provider_usage_metrics(request: Request, window_hours: int = 24) -> c.ProviderUsageMetricsReport:
    require_role(request, c.UserRole.operator)
    return service.provider_usage_metrics(request, window_hours)


@router.get("/api/ops/failure-taxonomy", response_model=c.PageResponse[c.FailureTaxonomyEntry])
def failure_taxonomy(
    request: Request,
    failure_class: str | None = None,
    run_id: str | None = None,
    case_id: str | None = None,
    limit: int = 50,
) -> c.PageResponse[c.FailureTaxonomyEntry]:
    require_role(request, c.UserRole.operator)
    return service.failure_taxonomy(request, failure_class, run_id, case_id, limit)


@router.get("/api/ops/failure-analysis", response_model=c.FailureAnalysisReport)
def failure_analysis(request: Request) -> c.FailureAnalysisReport:
    require_role(request, c.UserRole.operator)
    return service.failure_analysis(request)


@router.get("/api/ops/alert-rules", response_model=c.PageResponse[c.OpsAlertRule])
def alert_rules(request: Request, limit: int = 50) -> c.PageResponse[c.OpsAlertRule]:
    require_role(request, c.UserRole.operator)
    return service.list_alert_rules(request, limit)


@router.post("/api/ops/alert-rules", response_model=c.OpsAlertRule, status_code=201)
def upsert_alert_rule(payload: c.UpsertAlertRuleRequest, request: Request) -> c.OpsAlertRule:
    require_role(request, c.UserRole.admin)
    return service.upsert_alert_rule(payload, request)


@router.patch("/api/ops/alert-rules/{rule_id}", response_model=c.OpsAlertRule)
def patch_alert_rule(rule_id: str, payload: c.PatchAlertRuleRequest, request: Request) -> c.OpsAlertRule:
    require_role(request, c.UserRole.admin)
    return service.patch_alert_rule(rule_id, payload, request)


@router.get("/api/ops/budgets", response_model=c.PageResponse[c.Budget])
def budgets(request: Request, limit: int = 50) -> c.PageResponse[c.Budget]:

    return service.budgets(request, limit)


@router.post("/api/ops/budgets", response_model=c.Budget, status_code=201)
def upsert_budget(payload: c.UpsertBudgetRequest, request: Request) -> c.Budget:
    require_role(request, c.UserRole.admin)
    return service.upsert_budget(payload, request)


@router.patch("/api/ops/budgets/{budget_id}", response_model=c.Budget)
def patch_budget(budget_id: str, payload: c.PatchBudgetRequest, request: Request) -> c.Budget:
    require_role(request, c.UserRole.admin)
    return service.patch_budget(budget_id, payload, request)


@router.post("/api/ops/alerts/{event_id}/ack", response_model=c.OpsAlertEvent)
def ack_alert(event_id: str, payload: c.AcknowledgeAlertRequest, request: Request) -> c.OpsAlertEvent:
    require_role(request, c.UserRole.operator)
    return service.ack_alert(event_id, payload, request)


@router.post("/api/ops/alerts/{event_id}/resolve", response_model=c.OpsAlertEvent)
def resolve_alert(event_id: str, payload: c.ResolveAlertRequest, request: Request) -> c.OpsAlertEvent:
    require_role(request, c.UserRole.operator)
    return service.resolve_alert(event_id, payload, request)


@router.post("/api/runs/{run_id}/quality-checks", response_model=c.ProductionQualityCheck, status_code=201)
def run_quality_check(
    run_id: str, payload: c.CreateQualityCheckRequest, request: Request
) -> c.ProductionQualityCheck:
    require_role(request, c.UserRole.operator)
    return service.run_quality_check(run_id, payload, request)


@router.post(
    "/api/finished-videos/{id}/quality-checks",
    response_model=c.ProductionQualityCheck,
    status_code=201,
)
def finished_video_quality_check(
    id: str, payload: c.CreateQualityCheckRequest, request: Request
) -> c.ProductionQualityCheck:
    require_role(request, c.UserRole.operator)
    return service.finished_video_quality_check(id, payload, request)


@router.post("/api/approval-requests/{id}/approve", response_model=c.ApprovalRequest)
def approve_request(id: str, payload: c.ApprovalDecisionRequest, request: Request) -> c.ApprovalRequest:
    require_role(request, c.UserRole.operator)
    return service.approve_request(id, payload, request)


@router.post("/api/approval-requests/{id}/reject", response_model=c.ApprovalRequest)
def reject_request(id: str, payload: c.ApprovalDecisionRequest, request: Request) -> c.ApprovalRequest:
    require_role(request, c.UserRole.operator)
    return service.reject_request(id, payload, request)


@router.get("/api/audit/events", response_model=c.PageResponse[c.AuditEvent])
def audit_events(request: Request, limit: int = 50) -> c.PageResponse[c.AuditEvent]:
    require_role(request, c.UserRole.admin)
    return service.audit_events(request, limit)
