from __future__ import annotations

from packages.core.contracts import (
    ApprovalRequest,
    AuditEvent,
    Budget,
    CostRollup,
    FailureTaxonomyEntry,
    Money,
    OpsAlertEvent,
    OpsAlertRule,
    OpsScopeFilter,
    ProductionQualityCheck,
    YieldFunnelEvent,
)
from packages.core.storage.database import (
    ApprovalRequestRow,
    AuditEventRow,
    BudgetRow,
    CostRollupRow,
    FailureTaxonomyRow,
    OpsAlertEventRow,
    OpsAlertRuleRow,
    ProductionQualityCheckRow,
    YieldFunnelEventRow,
)
from packages.core.storage.row_mapper import map_row


def cost_rollup_row_to_contract(row: CostRollupRow) -> CostRollup:
    return map_row(
        row,
        CostRollup,
        estimated_cost=Money.model_validate(row.estimated_cost),
        actual_cost=Money.model_validate(row.actual_cost) if row.actual_cost else None,
    )


def budget_row_to_contract(row: BudgetRow) -> Budget:
    return map_row(
        row,
        Budget,
        period=row.period or "day",
        limit=Money.model_validate(row.limit),
        enforce=bool(row.enforce),
    )


def alert_rule_row_to_contract(row: OpsAlertRuleRow) -> OpsAlertRule:
    return map_row(
        row,
        OpsAlertRule,
        scope=OpsScopeFilter.model_validate(row.scope or {}),
        channels=list(row.channels or []),
    )


def failure_taxonomy_row_to_contract(row: FailureTaxonomyRow) -> FailureTaxonomyEntry:
    return map_row(row, FailureTaxonomyEntry)


def alert_row_to_contract(row: OpsAlertEventRow) -> OpsAlertEvent:
    return map_row(row, OpsAlertEvent)


def yield_event_row_to_contract(row: YieldFunnelEventRow) -> YieldFunnelEvent:
    return map_row(row, YieldFunnelEvent)


def quality_check_row_to_contract(row: ProductionQualityCheckRow) -> ProductionQualityCheck:
    return map_row(row, ProductionQualityCheck)


def approval_row_to_contract(row: ApprovalRequestRow) -> ApprovalRequest:
    return map_row(row, ApprovalRequest, resource_id=row.resource_id or row.id)


def audit_row_to_contract(row: AuditEventRow) -> AuditEvent:
    return map_row(row, AuditEvent)
