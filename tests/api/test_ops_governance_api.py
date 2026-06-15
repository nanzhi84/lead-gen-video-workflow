"""API coverage for the PR6 §9 governance endpoints (in-memory backend).

Exercises the new cost-metrics / failure-taxonomy / failure-analysis / alert-rules
endpoints plus the extended dashboard (cost_metrics / yield_rates / failure_analysis)
and the grouped cost-rollups, end to end against the in-memory repository.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.app import create_app


def _login(client: TestClient, email: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


def test_cost_metrics_endpoint_returns_spec_9_4_fields():
    with TestClient(create_app()) as client:
        _login(client, "admin@local.cutagent", "local-admin")
        response = client.get("/api/ops/cost-metrics")
        assert response.status_code == 200, response.text
        body = response.json()
        for field in (
            "estimated_cost",
            "wasted_cost",
            "retry_cost",
            "unit_cost_per_finished_video",
            "unit_cost_per_qc_passed_video",
            "unit_cost_per_published_video",
            "provider_cost",
            "model_cost",
            "prompt_version_cost",
        ):
            assert field in body


def test_cost_rollups_group_by_emits_one_row_per_group():
    with TestClient(create_app()) as client:
        _login(client, "admin@local.cutagent", "local-admin")
        grouped = client.get("/api/ops/cost-rollups", params={"group_by": "provider"})
        assert grouped.status_code == 200, grouped.text
        items = grouped.json()["items"]
        provider_rows = [i for i in items if i["group_by"] == "provider"]
        # Each provider row's group_key is a concrete provider id, NOT the literal
        # dimension name "provider" (the §26.1 GROUP BY fix).
        for row in provider_rows:
            assert row["group_key"] != "provider"
        # group_by=None still yields the overall cost_current_all row.
        overall = client.get("/api/ops/cost-rollups")
        assert any(i["id"] == "cost_current_all" for i in overall.json()["items"])


def test_yield_funnel_exposes_full_rate_set():
    with TestClient(create_app()) as client:
        _login(client, "admin@local.cutagent", "local-admin")
        response = client.get("/api/ops/yield-funnel")
        assert response.status_code == 200, response.text
        rates = response.json()["rates"]
        assert rates is not None
        for field in (
            "technical_success_rate",
            "finished_video_rate",
            "qc_pass_rate",
            "approval_pass_rate",
            "publish_success_rate",
            "true_yield_rate",
            "rework_rate",
            "discard_rate",
            "stage_pass_rate",
            "provider_success_rate",
            "prompt_version_yield",
        ):
            assert field in rates


def test_failure_taxonomy_records_qc_and_manual_rejection():
    with TestClient(create_app()) as client:
        _login(client, "admin@local.cutagent", "local-admin")
        # A failed run-level QC -> qc_failed in the taxonomy.
        qc = client.post(
            "/api/runs/run_fail_demo/quality-checks",
            json={"check_type": "manual", "result": "failed", "reason_code": "off_brand"},
        )
        assert qc.status_code == 201, qc.text
        # A manual rejection -> manual_rejected in the taxonomy.
        rejected = client.post(
            "/api/approval-requests/ar_fail_demo/reject", json={"reason": "no good"}
        )
        assert rejected.status_code == 200, rejected.text

        taxonomy = client.get("/api/ops/failure-taxonomy")
        assert taxonomy.status_code == 200, taxonomy.text
        classes = {item["failure_class"] for item in taxonomy.json()["items"]}
        assert "qc_failed" in classes
        assert "manual_rejected" in classes

        analysis = client.get("/api/ops/failure-analysis")
        assert analysis.status_code == 200, analysis.text
        analysis_body = analysis.json()
        assert analysis_body["total"] >= 2
        by_class = {i["failure_class"]: i["count"] for i in analysis_body["items"]}
        assert by_class.get("qc_failed", 0) >= 1
        assert by_class.get("manual_rejected", 0) >= 1


def test_alert_rules_crud_requires_admin_and_persists():
    with TestClient(create_app()) as client:
        _login(client, "viewer@local.cutagent", "local-viewer")
        forbidden = client.post(
            "/api/ops/alert-rules",
            json={
                "rule": {
                    "id": "rule_yield_drop",
                    "metric": "yield.true_yield_rate",
                    "condition": "lt",
                    "threshold": 0.5,
                }
            },
        )
        assert forbidden.status_code == 403, forbidden.text

    with TestClient(create_app()) as client:
        _login(client, "admin@local.cutagent", "local-admin")
        created = client.post(
            "/api/ops/alert-rules",
            json={
                "rule": {
                    "id": "rule_yield_drop",
                    "metric": "yield.true_yield_rate",
                    "condition": "lt",
                    "threshold": 0.5,
                    "severity": "warning",
                }
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["metric"] == "yield.true_yield_rate"

        patched = client.patch(
            "/api/ops/alert-rules/rule_yield_drop", json={"threshold": 0.7, "enabled": False}
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["threshold"] == 0.7
        assert patched.json()["enabled"] is False

        listed = client.get("/api/ops/alert-rules")
        assert listed.status_code == 200, listed.text
        assert any(item["id"] == "rule_yield_drop" for item in listed.json()["items"])


def test_dashboard_includes_governance_sections():
    with TestClient(create_app()) as client:
        _login(client, "admin@local.cutagent", "local-admin")
        response = client.get("/api/ops/dashboard")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["cost_metrics"] is not None
        assert body["yield_rates"] is not None
        assert body["failure_analysis"] is not None
        assert "budget_evaluations" in body
