from fastapi.testclient import TestClient

from apps.api.main import app


client = TestClient(app)


def test_fresh_import_accepts_all_spec_types():
    login = client.post(
        "/api/auth/login",
        json={"email": "admin@local.cutagent", "password": "local-admin"},
    )
    assert login.status_code == 200, login.text
    import_types = [
        "case",
        "script",
        "media",
        "finished_video",
        "video_version",
        "publish_record",
        "performance",
        "prompt_seed",
        "provider_price",
    ]
    for import_type in import_types:
        response = client.post(
            "/api/import/batches",
            json={"import_type": import_type, "rows": [{"external_id": f"ext_{import_type}"}]},
        )
        assert response.status_code == 202, response.text
        report = response.json()
        assert report["status"] == "completed"
        assert report["created_count"] == 1


def test_prometheus_metrics_contract_is_exposed():
    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.text
    assert "provider_cost_estimated_total" in body
    assert "yield_funnel_events_total" in body
    assert "temporal_activity_failures_total" in body
