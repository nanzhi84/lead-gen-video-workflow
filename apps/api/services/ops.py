from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import Request

from apps.api.common import (
    ops_repository,
    page,
    repository,
    request_id,
)
from packages.core import contracts as c
from packages.core.observability import compute_true_yield_rate, record_funnel_event
from packages.core.storage.repository import new_id
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


def _provider_usage_metrics_from_invocations(
    invocations: list[c.ProviderInvocation],
    *,
    window_hours: int,
) -> list[c.ProviderUsageMetricsItem]:
    window_start = c.utcnow() - timedelta(hours=window_hours)
    buckets: dict[tuple[str, str, str | None], dict[str, object]] = {}
    for invocation in invocations:
        if invocation.started_at < window_start:
            continue
        key = (invocation.provider_id, invocation.capability_id, invocation.model_id)
        bucket = buckets.setdefault(
            key,
            {
                "calls": 0,
                "success_count": 0,
                "amount": c.Decimal("0"),
                "currency": invocation.estimated_cost.currency if invocation.estimated_cost else "CNY",
            },
        )
        bucket["calls"] = int(bucket["calls"]) + 1
        if invocation.status == c.ProviderStatus.succeeded:
            bucket["success_count"] = int(bucket["success_count"]) + 1
        if invocation.estimated_cost is not None:
            bucket["amount"] = bucket["amount"] + invocation.estimated_cost.amount
            bucket["currency"] = invocation.estimated_cost.currency

    items: list[c.ProviderUsageMetricsItem] = []
    for (provider_id, capability_id, model_id), bucket in buckets.items():
        calls = int(bucket["calls"])
        success_count = int(bucket["success_count"])
        items.append(
            c.ProviderUsageMetricsItem(
                provider_id=provider_id,
                capability_id=capability_id,
                model_id=model_id,
                calls=calls,
                success_count=success_count,
                success_rate=(success_count / calls) if calls else 0,
                estimated_cost=c.Money(amount=bucket["amount"], currency=str(bucket["currency"])),
                window_hours=window_hours,
            )
        )
    return sorted(items, key=lambda item: (-item.calls, item.provider_id, item.capability_id, item.model_id or ""))


def provider_usage_metrics(request: Request, window_hours: int = 24) -> c.ProviderUsageMetricsReport:
    hours = max(1, min(window_hours, 24 * 30))
    if ops_repository(request) is not None:
        return ops_repository(request).provider_usage_metrics(window_hours=hours, request_id=request_id())
    return c.ProviderUsageMetricsReport(
        items=_provider_usage_metrics_from_invocations(
            list(repository(request).provider_invocations.values()),
            window_hours=hours,
        ),
        window_hours=hours,
        generated_at=c.utcnow(),
        request_id=request_id(),
    )


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
    repo = repository(request)
    events = []
    for event in repo.yield_events.values():
        run = repo.runs.get(event.run_id or "")
        if case_id is None or (run is not None and run.case_id == case_id):
            events.append(event)
    # §9.5: true_yield_rate must be run-scoped, NOT successes/total_events (the
    # denominator inflates as the taxonomy grows). A run is true-yield only if it
    # reached ``published`` and was never ``qc_failed`` / ``manual_rejected``.
    rate = compute_true_yield_rate(events)
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


def _qc_run_ids(repo, *, target_type: str, target_id: str) -> tuple[str | None, str | None]:
    """Best-effort (run_id, job_id) for a quality-check target so qc_* funnel
    events stay run-scoped. A ``run`` target IS the run; a ``finished_video``
    target resolves through the finished video's ``run_id``."""

    if target_type == "run":
        run = repo.runs.get(target_id)
        return (target_id if run is not None else target_id), getattr(run, "job_id", None)
    finished = repo.finished_videos.get(target_id) if target_id else None
    run_id = getattr(finished, "run_id", None) if finished else None
    run = repo.runs.get(run_id) if run_id else None
    return run_id, getattr(run, "job_id", None)


def _record_quality_check_funnel(repo, check: c.ProductionQualityCheck) -> None:
    """Emit the §9.5 qc_* stages for one quality check. Always records
    ``qc_started``; then ``qc_passed`` (result == passed) or ``qc_failed``
    (result == failed). ``warning`` / ``manual_required`` results emit only
    ``qc_started`` (the QC ran but did not terminally pass/fail). Best-effort —
    ``qc_failed`` disqualifies the run from true yield."""

    run_id, job_id = _qc_run_ids(repo, target_type=check.target_type, target_id=check.target_id)
    record_funnel_event(
        repo,
        event_type="qc_started",
        job_id=job_id,
        run_id=run_id,
        finished_video_id=check.target_id if check.target_type == "finished_video" else None,
        dedupe_key=f"{check.id}:qc_started",
        event_time=check.created_at,
    )
    result = check.result.value if hasattr(check.result, "value") else str(check.result)
    terminal = {"passed": "qc_passed", "failed": "qc_failed"}.get(result)
    if terminal is not None:
        record_funnel_event(
            repo,
            event_type=terminal,
            job_id=job_id,
            run_id=run_id,
            finished_video_id=check.target_id if check.target_type == "finished_video" else None,
            dedupe_key=f"{check.id}:{terminal}",
            event_time=check.created_at,
        )


def _approval_run_ids(repo, approval: c.ApprovalRequest) -> tuple[str | None, str | None]:
    """Best-effort (run_id, job_id) for an approval decision so manual_* funnel
    events stay run-scoped. Resolves a run/finished_video resource_id to its run."""

    resource_id = getattr(approval, "resource_id", None)
    if not resource_id:
        return None, None
    if resource_id in repo.runs:
        return resource_id, getattr(repo.runs[resource_id], "job_id", None)
    finished = repo.finished_videos.get(resource_id)
    run_id = getattr(finished, "run_id", None) if finished else None
    run = repo.runs.get(run_id) if run_id else None
    return run_id, getattr(run, "job_id", None)


def _record_approval_funnel(repo, approval: c.ApprovalRequest, *, decision: str) -> None:
    """Emit the §9.5 manual_* stage for one approval decision: ``manual_approved``
    (approved) or ``manual_rejected`` (rejected). Best-effort — ``manual_rejected``
    disqualifies the run from true yield."""

    event_type = "manual_approved" if decision == "approved" else "manual_rejected"
    run_id, job_id = _approval_run_ids(repo, approval)
    record_funnel_event(
        repo,
        event_type=event_type,
        job_id=job_id,
        run_id=run_id,
        dedupe_key=f"{approval.id}:{event_type}",
        event_time=approval.updated_at,
    )


def run_quality_check(
    run_id: str, payload: c.CreateQualityCheckRequest, request: Request
) -> c.ProductionQualityCheck:
    if ops_repository(request) is not None:
        return ops_repository(request).create_quality_check(
            target_type="run",
            target_id=run_id,
            payload=payload,
        )
    repo = repository(request)
    check = c.ProductionQualityCheck(id=new_id("qc"), target_type="run", target_id=run_id, **payload.model_dump())
    repo.quality_checks[check.id] = check
    _record_quality_check_funnel(repo, check)
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
    repo = repository(request)
    check = c.ProductionQualityCheck(
        id=new_id("qc"),
        target_type="finished_video",
        target_id=id,
        **payload.model_dump(),
    )
    repo.quality_checks[check.id] = check
    _record_quality_check_funnel(repo, check)
    return check


def approve_request(id: str, payload: c.ApprovalDecisionRequest, request: Request) -> c.ApprovalRequest:
    if ops_repository(request) is not None:
        return ops_repository(request).decide_approval(id, "approved", payload)
    repo = repository(request)
    existing = repo.approvals.get(id)
    approval = c.ApprovalRequest(
        id=id,
        resource_type=getattr(existing, "resource_type", None) or "approval_request",
        resource_id=getattr(existing, "resource_id", None) or id,
        status="approved",
        reason=payload.reason,
    )
    repo.approvals[id] = approval
    _record_approval_funnel(repo, approval, decision="approved")
    return approval


def reject_request(id: str, payload: c.ApprovalDecisionRequest, request: Request) -> c.ApprovalRequest:
    if ops_repository(request) is not None:
        return ops_repository(request).decide_approval(id, "rejected", payload)
    repo = repository(request)
    existing = repo.approvals.get(id)
    approval = c.ApprovalRequest(
        id=id,
        resource_type=getattr(existing, "resource_type", None) or "approval_request",
        resource_id=getattr(existing, "resource_id", None) or id,
        status="rejected",
        reason=payload.reason,
    )
    repo.approvals[id] = approval
    _record_approval_funnel(repo, approval, decision="rejected")
    return approval


def audit_events(request: Request, limit: int = 50) -> c.PageResponse[c.AuditEvent]:
    if ops_repository(request) is not None:
        values = ops_repository(request).list_audit_events(limit=limit)
        return c.PageResponse(items=values, total_hint=len(values), request_id=request_id())
    return page(repository(request).audit_events.values(), limit)
