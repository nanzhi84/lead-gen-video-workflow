from __future__ import annotations

from datetime import timedelta

from sqlalchemy import case, cast, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.sqltypes import Numeric

from packages.core.contracts import Money, ProviderUsageMetricsItem, ProviderUsageMetricsReport, utcnow
from packages.core.storage.database import ProviderInvocationRow


def sqlalchemy_provider_usage_metrics(
    session_factory: sessionmaker[Session],
    *,
    window_hours: int,
    request_id: str,
) -> ProviderUsageMetricsReport:
    generated_at = utcnow()
    window_start = generated_at - timedelta(hours=window_hours)
    amount = cast(ProviderInvocationRow.estimated_cost["amount"].astext, Numeric(20, 6))
    currency = ProviderInvocationRow.estimated_cost["currency"].astext
    success = case((ProviderInvocationRow.status == "succeeded", 1), else_=0)
    with session_factory() as session:
        statement = (
            select(
                ProviderInvocationRow.provider_id,
                ProviderInvocationRow.capability_id,
                ProviderInvocationRow.model_id,
                func.count(ProviderInvocationRow.id),
                func.sum(success),
                func.coalesce(func.sum(amount), 0),
                func.coalesce(func.max(currency), "CNY"),
            )
            .where(ProviderInvocationRow.started_at >= window_start)
            .group_by(
                ProviderInvocationRow.provider_id,
                ProviderInvocationRow.capability_id,
                ProviderInvocationRow.model_id,
            )
            .order_by(func.count(ProviderInvocationRow.id).desc())
        )
        rows = list(session.execute(statement))
    items = []
    for provider_id, capability_id, model_id, calls, success_count, total, currency_code in rows:
        call_count = int(calls or 0)
        successes = int(success_count or 0)
        items.append(
            ProviderUsageMetricsItem(
                provider_id=provider_id,
                capability_id=capability_id,
                model_id=model_id,
                calls=call_count,
                success_count=successes,
                success_rate=(successes / call_count) if call_count else 0,
                estimated_cost=Money(amount=total, currency=currency_code or "CNY"),
                window_hours=window_hours,
            )
        )
    return ProviderUsageMetricsReport(
        items=items,
        window_hours=window_hours,
        generated_at=generated_at,
        request_id=request_id,
    )
