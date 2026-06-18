"""Publish-account QR login + session validation API (sandbox driver)."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from apps.api.services import publish_login as publish_login_service
from apps.api.app import create_app
from packages.publishing import MemoryAccountsRepository
from packages.publishing.browser.driver import LoginHandle, LoginPollResult, SessionCheck
from packages.publishing.account_sessions import store_account_session


class _TrackingBrowserDriver:
    driver_id = "tracking"

    def __init__(
        self,
        *,
        poll_status: str = "pending",
        on_begin: Callable[[], None] | None = None,
        on_poll: Callable[[], None] | None = None,
        on_validate: Callable[[], None] | None = None,
    ) -> None:
        self.started: list[str] = []
        self.closed: list[str] = []
        self.poll_status = poll_status
        self.on_begin = on_begin
        self.on_poll = on_poll
        self.on_validate = on_validate

    def begin_login(self, platform: str) -> LoginHandle:
        self.started.append(platform)
        if self.on_begin is not None:
            self.on_begin()
        return LoginHandle(login_token=f"login_{platform}", qr_image="data:image/png;base64,tracking")

    def poll_login(self, login_token: str) -> LoginPollResult:
        if self.on_poll is not None:
            self.on_poll()
        if self.poll_status == "success":
            return LoginPollResult(status="success", storage_state_json='{"cookies": []}')
        return LoginPollResult(status="pending")

    def validate_session(self, platform: str, storage_state_json: str) -> SessionCheck:
        if self.on_validate is not None:
            self.on_validate()
        return SessionCheck(active=True)

    def close(self, login_token: str) -> None:
        self.closed.append(login_token)


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


def test_archived_account_rejects_login_and_validate():
    with TestClient(create_app()) as client:
        _login(client)
        account_id = _account(client)
        driver = _TrackingBrowserDriver()
        client.app.state.publish_browser_driver = driver
        assert client.delete(f"/api/publish/accounts/{account_id}").status_code == 200

        begin = client.post(f"/api/publish/accounts/{account_id}/login")
        assert begin.status_code == 404, begin.text
        assert driver.started == []

        validate = client.post(f"/api/publish/accounts/{account_id}/session:validate")
        assert validate.status_code == 404, validate.text


def test_begin_login_closes_driver_if_account_archived_during_start():
    with TestClient(create_app()) as client:
        _login(client)
        account_id = _account(client)
        repo = MemoryAccountsRepository(client.app.state.repository)
        driver = _TrackingBrowserDriver(on_begin=lambda: repo.archive_account(account_id))
        client.app.state.publish_browser_driver = driver

        begin = client.post(f"/api/publish/accounts/{account_id}/login")
        assert begin.status_code == 404, begin.text
        assert driver.started == ["douyin"]
        assert driver.closed == ["login_douyin"]
        assert client.app.state.publish_login_registry.get("login_douyin") is None


def test_cancel_login_closes_driver_session_and_removes_registry_entry():
    with TestClient(create_app()) as client:
        _login(client)
        account_id = _account(client)
        driver = _TrackingBrowserDriver()
        client.app.state.publish_browser_driver = driver

        begin = client.post(f"/api/publish/accounts/{account_id}/login")
        assert begin.status_code == 201, begin.text
        login_id = begin.json()["login_id"]
        assert client.app.state.publish_login_registry.get(login_id) is not None

        cancelled = client.delete(f"/api/publish/accounts/{account_id}/login/{login_id}")
        assert cancelled.status_code == 200, cancelled.text
        assert driver.closed == [login_id]
        assert client.app.state.publish_login_registry.get(login_id) is None

        poll = client.get(f"/api/publish/accounts/{account_id}/login/{login_id}")
        assert poll.status_code == 404, poll.text


def test_archiving_account_closes_pending_login_before_late_poll_can_store_session():
    with TestClient(create_app()) as client:
        _login(client)
        account_id = _account(client)
        driver = _TrackingBrowserDriver(poll_status="success")
        client.app.state.publish_browser_driver = driver

        begin = client.post(f"/api/publish/accounts/{account_id}/login")
        assert begin.status_code == 201, begin.text
        login_id = begin.json()["login_id"]
        assert client.app.state.publish_login_registry.get(login_id) is not None

        archived = client.delete(f"/api/publish/accounts/{account_id}")
        assert archived.status_code == 200, archived.text
        assert driver.closed == [login_id]
        assert client.app.state.publish_login_registry.get(login_id) is None

        poll = client.get(f"/api/publish/accounts/{account_id}/login/{login_id}")
        assert poll.status_code == 404, poll.text
        accounts = client.get("/api/publish/accounts?include_archived=true").json()["items"]
        account = next(item for item in accounts if item["id"] == account_id)
        assert account["status"] == "archived"
        assert account["has_session"] is False
        assert account["session_status"] == "never_logged_in"


def test_poll_success_does_not_report_active_when_session_store_loses_archive_race(
    monkeypatch,
):
    with TestClient(create_app()) as client:
        _login(client)
        account_id = _account(client)
        driver = _TrackingBrowserDriver(poll_status="success")
        client.app.state.publish_browser_driver = driver

        begin = client.post(f"/api/publish/accounts/{account_id}/login")
        assert begin.status_code == 201, begin.text
        login_id = begin.json()["login_id"]

        def archive_instead_of_store(repo, _store, target_account_id, _storage_state_json):
            assert target_account_id == account_id
            repo.archive_account(target_account_id)
            return None

        monkeypatch.setattr(
            publish_login_service,
            "store_account_session",
            archive_instead_of_store,
        )

        poll = client.get(f"/api/publish/accounts/{account_id}/login/{login_id}")
        assert poll.status_code == 404, poll.text
        assert driver.closed == [login_id]
        assert client.app.state.publish_login_registry.get(login_id) is None


def test_poll_pending_does_not_return_stale_state_when_account_archived_before_response():
    with TestClient(create_app()) as client:
        _login(client)
        account_id = _account(client)
        repo = MemoryAccountsRepository(client.app.state.repository)
        driver = _TrackingBrowserDriver(on_poll=lambda: repo.archive_account(account_id))
        client.app.state.publish_browser_driver = driver

        begin = client.post(f"/api/publish/accounts/{account_id}/login")
        assert begin.status_code == 201, begin.text
        login_id = begin.json()["login_id"]

        poll = client.get(f"/api/publish/accounts/{account_id}/login/{login_id}")
        assert poll.status_code == 404, poll.text
        assert driver.closed == [login_id]
        assert client.app.state.publish_login_registry.get(login_id) is None


def test_validate_session_does_not_report_active_when_account_archived_during_check():
    with TestClient(create_app()) as client:
        _login(client)
        account_id = _account(client)
        repo = MemoryAccountsRepository(client.app.state.repository)
        store_account_session(repo, client.app.state.secret_store, account_id, '{"cookies": []}')
        driver = _TrackingBrowserDriver(on_validate=lambda: repo.archive_account(account_id))
        client.app.state.publish_browser_driver = driver

        validate = client.post(f"/api/publish/accounts/{account_id}/session:validate")
        assert validate.status_code == 404, validate.text
        account = next(
            item
            for item in client.get("/api/publish/accounts?include_archived=true").json()["items"]
            if item["id"] == account_id
        )
        assert account["status"] == "archived"
        assert account["has_session"] is False


def test_validate_without_session_does_not_use_stale_account_after_archive(
    monkeypatch,
):
    with TestClient(create_app()) as client:
        _login(client)
        account_id = _account(client)
        original_get_ref = MemoryAccountsRepository.get_account_session_ref

        def archive_then_no_ref(self, target_account_id):
            assert target_account_id == account_id
            self.archive_account(target_account_id)
            return original_get_ref(self, target_account_id)

        monkeypatch.setattr(MemoryAccountsRepository, "get_account_session_ref", archive_then_no_ref)

        validate = client.post(f"/api/publish/accounts/{account_id}/session:validate")
        assert validate.status_code == 404, validate.text


def test_login_requires_auth():
    with TestClient(create_app()) as client:
        resp = client.post("/api/publish/accounts/whatever/login")
        assert resp.status_code in (401, 403), resp.text
