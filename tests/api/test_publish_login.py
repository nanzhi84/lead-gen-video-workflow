"""Publish-account QR login + session validation API (sandbox driver)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.app import create_app


def _login(client: TestClient) -> None:
    resp = client.post(
        "/api/auth/login", json={"email": "admin@local.cutagent", "password": "local-admin"}
    )
    assert resp.status_code == 200, resp.text


def _account(client: TestClient) -> str:
    client_id = client.post("/api/publish/clients", json={"name": "ACME"}).json()["id"]
    return client.post(
        "/api/publish/accounts",
        json={"client_id": client_id, "platform": "douyin", "account_name": "dy"},
    ).json()["id"]


def test_qr_login_flow_persists_session_and_validates():
    with TestClient(create_app()) as client:
        _login(client)
        account_id = _account(client)

        begin = client.post(f"/api/publish/accounts/{account_id}/login")
        assert begin.status_code == 201, begin.text
        body = begin.json()
        assert body["status"] == "pending"
        assert body["qr_image"].startswith("data:image/")
        assert begin.headers.get("cache-control") == "no-store"  # QR is a credential
        login_id = body["login_id"]

        statuses = []
        for _ in range(5):
            poll = client.get(f"/api/publish/accounts/{account_id}/login/{login_id}")
            assert poll.status_code == 200, poll.text
            statuses.append(poll.json()["status"])
            if poll.json()["status"] == "active":
                break
        assert "pending" in statuses and statuses[-1] == "active"

        val = client.post(f"/api/publish/accounts/{account_id}/session:validate")
        assert val.status_code == 200, val.text
        vbody = val.json()
        assert vbody["has_session"] is True
        assert vbody["session_status"] == "active"

        # no storage_state / secret ref leaks anywhere
        assert "session_secret_ref" not in vbody and "storage_state" not in vbody
        assert "storage_state" not in body


def test_validate_without_session_reports_no_session():
    with TestClient(create_app()) as client:
        _login(client)
        account_id = _account(client)
        val = client.post(f"/api/publish/accounts/{account_id}/session:validate")
        assert val.status_code == 200, val.text
        assert val.json()["has_session"] is False
        assert val.json()["session_status"] == "never_logged_in"


def test_login_unknown_account_404():
    with TestClient(create_app()) as client:
        _login(client)
        resp = client.post("/api/publish/accounts/ghost_account/login")
        assert resp.status_code == 404, resp.text


def test_login_requires_auth():
    with TestClient(create_app()) as client:
        resp = client.post("/api/publish/accounts/whatever/login")
        assert resp.status_code in (401, 403), resp.text
