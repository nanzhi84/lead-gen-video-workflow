"""§9.4 / §26.2 成本指标 computation.

Joins provider-invocation cost to §9.5 funnel counts to produce the 11 spec cost
indicators. Formulas (§26.2):

* ``unit_cost_per_finished_video``   = sum(cost) / count(finished_video_created).
* ``unit_cost_per_qc_passed_video``  = sum(cost) / count(qc_passed finished videos).
* ``unit_cost_per_published_video``  = sum(cost) / count(published, deduped by package).
* ``wasted_cost``  = cost of runs whose final state failed + cost tied to
                     qc_failed/manual_rejected/discarded finished videos.
* ``retry_cost``   = cost of runs with retry_of_run_id set + cost of node attempt > 1.
* ``cost_variance`` = actual_cost - estimated_cost (None until actual_cost backfilled).
* ``provider_cost`` / ``model_cost`` / ``prompt_version_cost`` = per-dimension cost.

All money is summed in ``Decimal`` micros-safe and returned as CNY ``Money``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from packages.core.contracts import CostMetrics, Money


@dataclass
class InvocationCost:
    """A flattened provider-invocation row for cost attribution."""

    estimated_amount: Decimal
    actual_amount: Decimal | None
    currency: str
    provider_id: str | None
    model_id: str | None
    prompt_version_id: str | None
    run_id: str | None
    run_is_failed: bool
    run_is_retry: bool
    node_attempt: int


@dataclass
class FunnelCounts:
    finished_video_count: int = 0
    qc_passed_count: int = 0
    published_count: int = 0
    # runs/finished videos whose cost is "wasted" (qc_failed/manual_rejected/discard)
    wasted_run_ids: frozenset[str] = frozenset()


def _money(amount: Decimal, currency: str = "CNY") -> Money:
    return Money(amount=amount, currency=currency)


def _unit_cost(total: Decimal, count: int, currency: str) -> Money | None:
    if count <= 0:
        return None
    return _money(total / Decimal(count), currency)


def compute_cost_metrics(
    invocations: Iterable[InvocationCost],
    counts: FunnelCounts,
    *,
    currency: str = "CNY",
    window_start=None,
    window_end=None,
) -> CostMetrics:
    invocations = list(invocations)
    total_estimated = Decimal("0")
    total_actual = Decimal("0")
    has_actual = False
    wasted = Decimal("0")
    retry = Decimal("0")
    provider_cost: dict[str, Decimal] = {}
    model_cost: dict[str, Decimal] = {}
    prompt_version_cost: dict[str, Decimal] = {}

    for inv in invocations:
        cost = inv.estimated_amount or Decimal("0")
        total_estimated += cost
        if inv.actual_amount is not None:
            total_actual += inv.actual_amount
            has_actual = True

        if inv.provider_id:
            provider_cost[inv.provider_id] = provider_cost.get(inv.provider_id, Decimal("0")) + cost
        if inv.model_id:
            model_cost[inv.model_id] = model_cost.get(inv.model_id, Decimal("0")) + cost
        if inv.prompt_version_id:
            prompt_version_cost[inv.prompt_version_id] = (
                prompt_version_cost.get(inv.prompt_version_id, Decimal("0")) + cost
            )

        # §26.2 wasted_cost: failed runs OR runs feeding a disqualified/discarded video.
        if inv.run_is_failed or (inv.run_id and inv.run_id in counts.wasted_run_ids):
            wasted += cost
        # §26.2 retry_cost: retry runs OR node attempt > 1.
        if inv.run_is_retry or inv.node_attempt > 1:
            retry += cost

    cost_variance: Money | None = None
    actual_money: Money | None = None
    if has_actual:
        actual_money = _money(total_actual, currency)
        cost_variance = _money(total_actual - total_estimated, currency)

    return CostMetrics(
        window_start=window_start,
        window_end=window_end,
        estimated_cost=_money(total_estimated, currency),
        actual_cost=actual_money,
        cost_variance=cost_variance,
        wasted_cost=_money(wasted, currency),
        retry_cost=_money(retry, currency),
        finished_video_count=counts.finished_video_count,
        qc_passed_count=counts.qc_passed_count,
        published_count=counts.published_count,
        unit_cost_per_finished_video=_unit_cost(total_estimated, counts.finished_video_count, currency),
        unit_cost_per_qc_passed_video=_unit_cost(total_estimated, counts.qc_passed_count, currency),
        unit_cost_per_published_video=_unit_cost(total_estimated, counts.published_count, currency),
        provider_cost={k: _money(v, currency) for k, v in provider_cost.items()},
        model_cost={k: _money(v, currency) for k, v in model_cost.items()},
        prompt_version_cost={k: _money(v, currency) for k, v in prompt_version_cost.items()},
    )
