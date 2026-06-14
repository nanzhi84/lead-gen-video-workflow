from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from packages.core.contracts import (
    ApprovalDecisionRequest,
    ApprovalRequest,
    AuditEvent,
    Budget,
    CostRollup,
    CreateQualityCheckRequest,
    ErrorCode,
    Money,
    OpsAlertEvent,
    OpsDashboardVm,
    PatchBudgetRequest,
    ProductionQualityCheck,
    ProviderUsageReport,
    ProviderUsageMetricsReport,
    ReconcileBillingRequest,
    ReconcileBillingResponse,
    UpsertBudgetRequest,
    YieldFunnelResponse,
    utcnow,
)
from packages.core.storage.database import (
    ApprovalRequestRow,
    AuditEventRow,
    BudgetRow,
    CostRollupRow,
    OpsAlertEventRow,
    ProviderInvocationRow,
    ProductionQualityCheckRow,
    YieldFunnelEventRow,
)
from packages.core.observability import compute_true_yield_rate
from packages.core.storage.repository import new_id
from packages.core.workflow import NodeExecutionError
from packages.ops.sqlalchemy_mappers import (
    alert_row_to_contract,
    approval_row_to_contract,
    audit_row_to_contract,
    budget_row_to_contract,
    cost_rollup_row_to_contract,
    quality_check_row_to_contract,
    yield_event_row_to_contract,
)
from packages.ops.provider_usage_metrics import sqlalchemy_provider_usage_metrics


class SqlAlchemyOpsRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def dashboard(self, window_start: datetime | None = None, window_end: datetime | None = None) -> OpsDashboardVm:
        return OpsDashboardVm(
            usage=self.provider_usage(window_start=window_start, window_end=window_end),
            yield_funnel=self.yield_funnel(window_start=window_start, window_end=window_end),
            alerts=self.list_alerts(),
            cost_rollups=self.list_cost_rollups(limit=50),
        )

    def provider_usage(
        self,
        *,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
        provider_id: str | None = None,
        case_id: str | None = None,
    ) -> ProviderUsageReport:
        with self.session_factory() as session:
            statement = select(ProviderInvocationRow)
            if provider_id:
                statement = statement.where(ProviderInvocationRow.provider_id == provider_id)
            if case_id:
                statement = statement.where(ProviderInvocationRow.case_id == case_id)
            if window_start:
                statement = statement.where(ProviderInvocationRow.created_at >= window_start)
            if window_end:
                statement = statement.where(ProviderInvocationRow.created_at <= window_end)
            rows = list(session.scalars(statement))
        estimated = sum(
            (
                Money.model_validate(row.estimated_cost).amount
                for row in rows
                if row.estimated_cost is not None
            ),
            Money(amount=0, currency="CNY").amount,
        )
        unpriced = len([row for row in rows if row.billing_status == "unpriced"])
        return ProviderUsageReport(
            invocations=len(rows),
            estimated_cost=Money(amount=estimated, currency="CNY"),
            unpriced_invocation_count=unpriced,
        )

    def provider_usage_metrics(self, *, window_hours: int = 24, request_id: str) -> ProviderUsageMetricsReport:
        return sqlalchemy_provider_usage_metrics(
            self.session_factory,
            window_hours=window_hours,
            request_id=request_id,
        )

    def list_cost_rollups(
        self,
        *,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
        group_by: str | None = None,
        limit: int = 50,
    ) -> list[CostRollup]:
        with self.session_factory() as session:
            usage = self.provider_usage(window_start=window_start, window_end=window_end)
            rollup_id = f"cost_current_{group_by or 'all'}"
            row = session.get(CostRollupRow, rollup_id)
            if row is None:
                row = CostRollupRow(
                    id=rollup_id,
                    group_key=group_by or "all",
                    group_by=group_by,
                    estimated_cost=usage.estimated_cost.model_dump(mode="json"),
                    actual_cost=None,
                    invocations=usage.invocations,
                )
                session.add(row)
            else:
                row.group_key = group_by or "all"
                row.group_by = group_by
                row.estimated_cost = usage.estimated_cost.model_dump(mode="json")
                row.invocations = usage.invocations
                row.updated_at = utcnow()
            session.commit()
            statement = select(CostRollupRow).order_by(CostRollupRow.updated_at.desc()).limit(limit)
            return [cost_rollup_row_to_contract(item) for item in session.scalars(statement)]

    def yield_funnel(
        self,
        *,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
        case_id: str | None = None,
    ) -> YieldFunnelResponse:
        with self.session_factory() as session:
            statement = select(YieldFunnelEventRow)
            if case_id:
                statement = statement.where(YieldFunnelEventRow.case_id == case_id)
            if window_start:
                statement = statement.where(YieldFunnelEventRow.created_at >= window_start)
            if window_end:
                statement = statement.where(YieldFunnelEventRow.created_at <= window_end)
            events = [yield_event_row_to_contract(row) for row in session.scalars(statement)]
        # §9.5: true_yield_rate is run-scoped (distinct runs that reached
        # ``published`` and were never ``qc_failed`` / ``manual_rejected``) over
        # distinct runs that entered the funnel — NOT successes/total_events,
        # which inflates as the taxonomy grows.
        rate = compute_true_yield_rate(events)
        return YieldFunnelResponse(events=events, true_yield_rate=rate)

    def list_budgets(self, *, limit: int = 50) -> list[Budget]:
        with self.session_factory() as session:
            statement = select(BudgetRow).order_by(BudgetRow.updated_at.desc()).limit(limit)
            return [budget_row_to_contract(row) for row in session.scalars(statement)]

    def upsert_budget(self, payload: UpsertBudgetRequest) -> Budget:
        budget = payload.budget
        with self.session_factory() as session:
            row = BudgetRow(
                id=budget.id,
                scope_type=budget.scope_type,
                scope_id=budget.scope_id,
                limit=budget.limit.model_dump(mode="json"),
                alert_threshold=budget.alert_threshold,
                enabled=budget.enabled,
                schema_version=budget.schema_version,
                created_at=budget.created_at,
                updated_at=utcnow(),
            )
            merged = session.merge(row)
            session.commit()
            session.refresh(merged)
            return budget_row_to_contract(merged)

    def patch_budget(self, budget_id: str, payload: PatchBudgetRequest) -> Budget:
        with self.session_factory() as session:
            row = session.get(BudgetRow, budget_id)
            if row is None:
                raise NodeExecutionError(ErrorCode.validation_invalid_options, "Budget not found.")
            updates = payload.model_dump(exclude_none=True)
            if "limit" in updates:
                row.limit = payload.limit.model_dump(mode="json") if payload.limit else row.limit
            if "alert_threshold" in updates:
                row.alert_threshold = updates["alert_threshold"]
            if "enabled" in updates:
                row.enabled = updates["enabled"]
            row.updated_at = utcnow()
            session.commit()
            session.refresh(row)
            return budget_row_to_contract(row)

    def list_alerts(self, *, limit: int = 50) -> list[OpsAlertEvent]:
        with self.session_factory() as session:
            statement = select(OpsAlertEventRow).order_by(OpsAlertEventRow.updated_at.desc()).limit(limit)
            return [alert_row_to_contract(row) for row in session.scalars(statement)]

    def patch_alert_status(self, event_id: str, status: str) -> OpsAlertEvent:
        with self.session_factory() as session:
            row = session.get(OpsAlertEventRow, event_id)
            if row is None:
                raise NodeExecutionError(ErrorCode.validation_invalid_options, "Alert not found.")
            row.status = status
            row.updated_at = utcnow()
            session.commit()
            session.refresh(row)
            return alert_row_to_contract(row)

    def create_quality_check(
        self, *, target_type: str, target_id: str, payload: CreateQualityCheckRequest
    ) -> ProductionQualityCheck:
        with self.session_factory() as session:
            row = ProductionQualityCheckRow(
                id=new_id("qc"),
                target_type=target_type,
                target_id=target_id,
                check_type=payload.check_type,
                result=payload.result,
                reason_code=payload.reason_code,
                evidence_artifact_id=payload.evidence_artifact_id,
                affects_true_yield=payload.affects_true_yield,
            )
            session.add(row)
            self._record_audit(
                session,
                action="quality_check.created",
                resource_type=target_type,
                resource_id=target_id,
                details={"quality_check_id": row.id, "result": payload.result},
            )
            session.commit()
            session.refresh(row)
            return quality_check_row_to_contract(row)

    def decide_approval(
        self, approval_id: str, status: str, payload: ApprovalDecisionRequest
    ) -> ApprovalRequest:
        with self.session_factory() as session:
            row = session.get(ApprovalRequestRow, approval_id)
            if row is None:
                row = ApprovalRequestRow(
                    id=approval_id,
                    resource_type="approval_request",
                    resource_id=approval_id,
                    status=status,
                    reason=payload.reason,
                )
                session.add(row)
            else:
                row.status = status
                row.reason = payload.reason
                row.updated_at = utcnow()
            self._record_audit(
                session,
                action=f"approval.{status}",
                resource_type=row.resource_type,
                resource_id=row.resource_id or approval_id,
                details={"approval_id": approval_id, "reason": payload.reason},
            )
            session.commit()
            session.refresh(row)
            return approval_row_to_contract(row)

    def list_audit_events(self, *, limit: int = 50) -> list[AuditEvent]:
        with self.session_factory() as session:
            statement = select(AuditEventRow).order_by(AuditEventRow.created_at.desc()).limit(limit)
            return [audit_row_to_contract(row) for row in session.scalars(statement)]

    def reconcile_billing(self, payload: ReconcileBillingRequest, request_id: str) -> ReconcileBillingResponse:
        reconciliation_run_id = new_id("recon")
        with self.session_factory() as session:
            self._record_audit(
                session,
                action="billing.reconcile_requested",
                resource_type="provider_billing",
                resource_id=payload.provider_id,
                details={
                    "reconciliation_run_id": reconciliation_run_id,
                    "provider_id": payload.provider_id,
                    "window_start": payload.window_start.isoformat(),
                    "window_end": payload.window_end.isoformat(),
                    "dry_run": payload.dry_run,
                },
            )
            session.commit()
        return ReconcileBillingResponse(
            reconciliation_run_id=reconciliation_run_id,
            status="queued",
            request_id=request_id,
        )

    def _record_audit(
        self,
        session: Session,
        *,
        action: str,
        resource_type: str,
        resource_id: str | None,
        details: dict,
    ) -> None:
        session.add(
            AuditEventRow(
                id=new_id("audit"),
                actor="system",
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                details=details,
            )
        )
