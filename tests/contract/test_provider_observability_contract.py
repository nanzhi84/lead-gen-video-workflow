from decimal import Decimal

from packages.core.contracts import (
    Money,
    ProviderBalanceItem,
    ProviderBalanceReport,
    ProviderUsageMetricsItem,
    ProviderUsageMetricsReport,
    utcnow,
)


def test_provider_balance_contract_supports_snapshot_statuses_and_report_state():
    item = ProviderBalanceItem(
        provider_id="deepseek",
        account_group="deepseek.prod",
        balance=Money(amount=Decimal("1.5"), currency="CNY"),
        checked_at=utcnow(),
        status="ok",
        detail=None,
    )
    report = ProviderBalanceReport(items=[item], status="ok", request_id="req_1")

    assert report.items[0].status == "ok"
    assert ProviderBalanceReport(items=[], status="pending", request_id="req_2").status == "pending"
    assert ProviderBalanceItem(provider_id="kimi", checked_at=utcnow(), status="unauthorized").status == "unauthorized"
    assert (
        ProviderBalanceItem(provider_id="minimax.tts", checked_at=utcnow(), status="unsupported").status
        == "unsupported"
    )


def test_provider_usage_metrics_report_contract_groups_provider_capability_model():
    item = ProviderUsageMetricsItem(
        provider_id="deepseek",
        capability_id="llm.chat",
        model_id="deepseek-chat",
        calls=2,
        success_count=1,
        success_rate=0.5,
        estimated_cost=Money(amount=Decimal("0.15"), currency="CNY"),
        window_hours=24,
    )
    report = ProviderUsageMetricsReport(items=[item], window_hours=24, generated_at=utcnow(), request_id="req_1")

    assert report.items[0].provider_id == "deepseek"
    assert report.items[0].success_rate == 0.5
    assert report.items[0].estimated_cost.amount == Decimal("0.15")
