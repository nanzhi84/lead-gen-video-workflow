"""Publish-account CDP login + live login-state API."""

from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Queue

from fastapi.testclient import TestClient

from apps.api.app import create_app
from packages.core import contracts as c
from packages.core.contracts import PlatformAccount


@dataclass
class _Snapshot:
    login_id: str
    account_id: str
    platform: str
    status: str = "pending"
    detail: str | None = None
    login_state: c.PublishLoginState = "unknown"


class _FakeLoginManager:
    def __init__(
        self,
        *,
        complete_on_begin: bool = True,
        accounts: list[PlatformAccount] | None = None,
        available: bool = True,
    ) -> None:
        self.complete_on_begin = complete_on_begin
        self.accounts = accounts or []
        self.available = available
        self.started: list[str] = []
        self.cancelled: list[str] = []
        self.sessions: dict[str, _Snapshot] = {}
        self.events: dict[str, Queue[c.LoginStreamEvent]] = {}

    def probe_accounts(self):
        if not self.available:
            return [], False, "小V猫不可达"
        return list(self.accounts), True, None

    def begin(self, login_id: str, account: c.PublishAccount, *, on_account):
        self.started.append(account.platform)
        snapshot = _Snapshot(login_id=login_id, account_id=account.id, platform=account.platform)
        self.sessions[login_id] = snapshot
        queue: Queue[c.LoginStreamEvent] = Queue()
        self.events[login_id] = queue
        queue.put(c.LoginStreamEvent(type="qr", qr_image="data:image/png;base64,qr"))
        if self.complete_on_begin:
            platform_account = PlatformAccount(
                uid="xvm-123",
                platform=account.platform,
                nickname=account.account_name,
                is_login=True,
            )
            self.accounts = [platform_account]
            updated = on_account(platform_account)
            snapshot.status = "active"
            snapshot.login_state = "logged_in"
            queue.put(c.LoginStreamEvent(type="status", status="active"))
            queue.put(c.LoginStreamEvent(type="account", account=updated))
        return snapshot

    def poll(self, login_id: str):
        return self.sessions.get(login_id)

    def cancel(self, login_id: str) -> bool:
        if login_id not in self.sessions:
            return False
        self.cancelled.append(login_id)
        self.sessions.pop(login_id, None)
        return True

    def next_event(self, login_id: str, timeout: float = 30):
        queue = self.events.get(login_id)
        if queue is None:
            return None
        try:
            return queue.get(timeout=timeout)
        except Empty:
            return None


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


def test_login_flow_streams_qr_binds_xiaovmao_uid_and_validates():
    with TestClient(create_app()) as client:
        _login(client)
        account_id = _account(client)
        manager = _FakeLoginManager()
        client.app.state.xiaovmao_login_manager = manager

        begin = client.post(f"/api/publish/accounts/{account_id}/login")
        assert begin.status_code == 201, begin.text
        body = begin.json()
        assert body["status"] == "pending"
        assert "qr_image" not in body
        assert body["stream_path"] == f"/api/publish/accounts/login/{body['login_id']}/stream"
        assert begin.headers.get("cache-control") == "no-store"

        with client.websocket_connect(body["stream_path"]) as websocket:
            event = websocket.receive_json()
        assert event["type"] == "qr"
        assert event["qr_image"].startswith("data:image/")

        poll = client.get(f"/api/publish/accounts/{account_id}/login/{body['login_id']}")
        assert poll.status_code == 200, poll.text
        assert poll.json()["status"] == "active"
        assert poll.json()["login_state"] == "logged_in"

        listed = client.get("/api/publish/accounts").json()["items"][0]
        assert listed["xiaovmao_uid"] == "xvm-123"
        assert listed["login_state"] == "logged_in"

        val = client.post(f"/api/publish/accounts/{account_id}/session:validate")
        assert val.status_code == 200, val.text
        assert val.json()["login_state"] == "logged_in"
        assert "session_secret_ref" not in val.json() and "storage_state" not in val.json()


def test_validate_without_matching_xiaovmao_account_reports_logged_out():
    with TestClient(create_app()) as client:
        _login(client)
        account_id = _account(client)
        client.app.state.xiaovmao_login_manager = _FakeLoginManager(
            complete_on_begin=False, accounts=[]
        )

        val = client.post(f"/api/publish/accounts/{account_id}/session:validate")
        assert val.status_code == 200, val.text
        assert val.json()["login_state"] == "logged_out"


def test_xiaovmao_unavailable_degrades_login_state_to_unknown():
    with TestClient(create_app()) as client:
        _login(client)
        account_id = _account(client)
        client.app.state.xiaovmao_login_manager = _FakeLoginManager(
            complete_on_begin=False, available=False
        )

        listed = client.get("/api/publish/accounts").json()["items"][0]
        assert listed["login_state"] == "unknown"
        val = client.post(f"/api/publish/accounts/{account_id}/session:validate")
        assert val.status_code == 200, val.text
        assert val.json()["login_state"] == "unknown"


def test_cancel_login_ends_manager_session_and_removes_poll_result():
    with TestClient(create_app()) as client:
        _login(client)
        account_id = _account(client)
        manager = _FakeLoginManager(complete_on_begin=False)
        client.app.state.xiaovmao_login_manager = manager

        begin = client.post(f"/api/publish/accounts/{account_id}/login")
        assert begin.status_code == 201, begin.text
        login_id = begin.json()["login_id"]

        cancelled = client.delete(f"/api/publish/accounts/{account_id}/login/{login_id}")
        assert cancelled.status_code == 200, cancelled.text
        assert manager.cancelled == [login_id]

        poll = client.get(f"/api/publish/accounts/{account_id}/login/{login_id}")
        assert poll.status_code == 404, poll.text


def test_archived_account_rejects_login_and_validate():
    with TestClient(create_app()) as client:
        _login(client)
        account_id = _account(client)
        client.app.state.xiaovmao_login_manager = _FakeLoginManager()
        assert client.delete(f"/api/publish/accounts/{account_id}").status_code == 200

        begin = client.post(f"/api/publish/accounts/{account_id}/login")
        assert begin.status_code == 404, begin.text
        validate = client.post(f"/api/publish/accounts/{account_id}/session:validate")
        assert validate.status_code == 404, validate.text


def test_login_requires_auth():
    with TestClient(create_app()) as client:
        resp = client.post("/api/publish/accounts/whatever/login")
        assert resp.status_code in (401, 403), resp.text
