from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app


def _metric_value(metrics_text: str, name: str) -> float:
    for line in metrics_text.splitlines():
        if line.startswith(name + " "):
            return float(line.rsplit(" ", 1)[-1])
    raise AssertionError(f"Metric {name} not found.")


def test_metrics_api_request_count_increases_after_request() -> None:
    with TestClient(app) as client:
        before = client.get("/metrics")
        assert before.status_code == 200
        before_count = _metric_value(before.text, "api_request_duration_seconds_count")

        health = client.get("/api/health")
        assert health.status_code == 200

        after = client.get("/metrics")
        assert after.status_code == 200
        after_count = _metric_value(after.text, "api_request_duration_seconds_count")

    assert after_count > before_count
    assert "outbox_lag_seconds" in after.text
