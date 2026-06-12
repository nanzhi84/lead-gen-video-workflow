from decimal import Decimal

from fastapi.testclient import TestClient

from apps.api.app import create_app
from packages.core.contracts import (
    Money,
    ProviderBalanceSnapshot,
    ProviderInvocation,
    ProviderStatus,
    utcnow,
)


def login_admin(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"email": "admin@local.cutagent", "password": "local-admin"})
    assert response.status_code == 200, response.text


def test_provider_balances_reads_snapshots_instead_of_mock_values():
    app = create_app()

    with TestClient(app) as client:
        snapshot = ProviderBalanceSnapshot(
            id="pbs_deepseek",
            provider_id="deepseek",
            account_group="deepseek.prod",
            balance=Money(amount=Decimal("42.5"), currency="CNY"),
            quota_remaining=10,
            unit="credits",
            status="ok",
            checked_at=utcnow(),
        )
        app.state.repository.provider_balance_snapshots[snapshot.id] = snapshot
        login_admin(client)
        response = client.get("/api/providers/balances", params={"provider_id": "deepseek"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["items"][0]["provider_id"] == "deepseek"
    assert body["items"][0]["balance"]["amount"] == "42.5"
    assert body["items"][0]["quota_remaining"] == 10


def test_provider_balances_without_snapshots_returns_pending_empty_report():
    with TestClient(create_app()) as client:
        login_admin(client)
        response = client.get("/api/providers/balances", params={"provider_id": "deepseek"})

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending"
    assert response.json()["items"] == []


def test_refresh_provider_balances_writes_snapshots_without_real_network():
    with TestClient(create_app()) as client:
        login_admin(client)
        response = client.post("/api/providers/balances/refresh")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["items"]
    statuses = {item["status"] for item in body["items"]}
    assert statuses <= {"unconfigured", "unsupported"}
    assert all(item.get("balance") is None for item in body["items"] if item["status"] != "ok")


def test_provider_usage_metrics_groups_invocations_by_provider_capability_and_model():
    app = create_app()

    with TestClient(app) as client:
        now = utcnow()
        app.state.repository.provider_invocations["pinv_1"] = ProviderInvocation(
            id="pinv_1",
            provider_id="deepseek",
            model_id="deepseek-chat",
            provider_profile_id="deepseek.prod",
            capability_id="llm.chat",
            status=ProviderStatus.succeeded,
            estimated_cost=Money(amount=Decimal("0.10"), currency="CNY"),
            started_at=now,
        )
        app.state.repository.provider_invocations["pinv_2"] = ProviderInvocation(
            id="pinv_2",
            provider_id="deepseek",
            model_id="deepseek-chat",
            provider_profile_id="deepseek.prod",
            capability_id="llm.chat",
            status=ProviderStatus.failed,
            estimated_cost=Money(amount=Decimal("0.05"), currency="CNY"),
            started_at=now,
        )
        app.state.repository.provider_invocations["pinv_3"] = ProviderInvocation(
            id="pinv_3",
            provider_id="kimi",
            model_id="moonshot-v1",
            provider_profile_id="kimi.prod",
            capability_id="llm.chat",
            status=ProviderStatus.succeeded,
            estimated_cost=Money(amount=Decimal("0.20"), currency="CNY"),
            started_at=now,
        )
        login_admin(client)
        response = client.get("/api/ops/provider-usage-metrics", params={"window_hours": 24})

    assert response.status_code == 200, response.text
    body = response.json()
    deepseek = next(item for item in body["items"] if item["provider_id"] == "deepseek")
    assert deepseek["capability_id"] == "llm.chat"
    assert deepseek["model_id"] == "deepseek-chat"
    assert deepseek["calls"] == 2
    assert deepseek["success_count"] == 1
    assert deepseek["success_rate"] == 0.5
    assert deepseek["estimated_cost"]["amount"] == "0.15"
    assert body["window_hours"] == 24
