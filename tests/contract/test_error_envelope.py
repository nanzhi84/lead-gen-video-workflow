from fastapi.testclient import TestClient

from apps.api.main import app


def assert_error_envelope(response, status_code: int, code: str) -> None:
    assert response.status_code == status_code, response.text
    body = response.json()
    assert body["error"]["code"] == code
    assert body["error"]["request_id"]
    assert response.headers["X-Request-Id"] == body["error"]["request_id"]


def test_422_validation_error_uses_unified_error_envelope_and_request_id():
    client = TestClient(app)

    response = client.post("/api/auth/login", json={"email": "admin@local.cutagent"})

    assert_error_envelope(response, 422, "validation.invalid_options")


def test_404_domain_error_uses_unified_error_envelope_and_request_id():
    client = TestClient(app)
    login = client.post(
        "/api/auth/login",
        json={"email": "admin@local.cutagent", "password": "local-admin"},
    )
    assert login.status_code == 200, login.text

    response = client.get("/api/cases/case_missing")

    assert_error_envelope(response, 404, "validation.missing_case")


def test_409_conflict_error_uses_same_request_id_within_request():
    client = TestClient(app)
    login = client.post(
        "/api/auth/login",
        json={"email": "admin@local.cutagent", "password": "local-admin"},
    )
    assert login.status_code == 200, login.text

    headers = {"Idempotency-Key": "error-envelope-conflict"}
    first = client.post("/api/cases", json={"name": "Envelope Case"}, headers=headers)
    assert first.status_code == 201, first.text
    response = client.post("/api/cases", json={"name": "Different Envelope Case"}, headers=headers)

    assert_error_envelope(response, 409, "idempotency.conflict")
