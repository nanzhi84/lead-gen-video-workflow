"""Publish-account API: clients / accounts / case targets (memory backend)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.app import create_app
from apps.api.services import publish_login
from packages.publishing import MemoryAccountsRepository


def _login(client: TestClient) -> None:
    resp = client.post(
        "/api/auth/login", json={"email": "admin@local.cutagent", "password": "local-admin"}
    )
    assert resp.status_code == 200, resp.text


def _new_client(client: TestClient, name: str = "ACME") -> str:
    resp = client.post("/api/publish/clients", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_account(
    client: TestClient, client_id: str, platform: str, name: str, *, platform_uid: str | None = None
) -> str:
    payload = {"client_id": client_id, "platform": platform, "account_name": name}
    if platform_uid is not None:
        payload["platform_uid"] = platform_uid
    resp = client.post(
        "/api/publish/accounts",
        json=payload,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _complete_login(client: TestClient, account_id: str) -> None:
    begin = client.post(f"/api/publish/accounts/{account_id}/login")
    assert begin.status_code == 201, begin.text
    login_id = begin.json()["login_id"]
    for _ in range(5):
        poll = client.get(f"/api/publish/accounts/{account_id}/login/{login_id}")
        assert poll.status_code == 200, poll.text
        if poll.json()["status"] == "active":
            return
    raise AssertionError("login did not become active")


def test_client_and_account_crud_and_dedup():
    with TestClient(create_app()) as client:
        _login(client)
        client_id = _new_client(client, "ACME")

        clients = client.get("/api/publish/clients")
        assert clients.status_code == 200
        assert any(item["id"] == client_id for item in clients.json()["items"])

        created = client.post(
            "/api/publish/accounts",
            json={"client_id": client_id, "platform": "douyin", "account_name": "acme-dy"},
        )
        assert created.status_code == 201, created.text
        account = created.json()
        assert account["client_id"] == client_id
        assert account["has_session"] is False
        assert account["session_status"] == "never_logged_in"
        assert "session_secret_ref" not in account  # secret ref never leaks

        dup = client.post(
            "/api/publish/accounts",
            json={"client_id": client_id, "platform": "douyin", "account_name": "acme-dy"},
        )
        assert 400 <= dup.status_code < 500, dup.text  # validation.conflict

        bad = client.post(
            "/api/publish/accounts",
            json={"client_id": "nope", "platform": "douyin", "account_name": "x"},
        )
        assert 400 <= bad.status_code < 500, bad.text


def test_account_list_filters_and_no_secret_leak():
    with TestClient(create_app()) as client:
        _login(client)
        client_id = _new_client(client)
        _new_account(client, client_id, "douyin", "dy")
        _new_account(client, client_id, "kuaishou", "ks")

        dy = client.get(f"/api/publish/accounts?client_id={client_id}&platform=douyin")
        assert dy.status_code == 200
        items = dy.json()["items"]
        assert len(items) == 1 and items[0]["platform"] == "douyin"
        assert all("session_secret_ref" not in item for item in items)


def test_case_targets_same_client_enforced_and_replace():
    with TestClient(create_app()) as client:
        _login(client)
        c1 = _new_client(client, "C1")
        c2 = _new_client(client, "C2")
        a1 = _new_account(client, c1, "douyin", "a1")
        a2 = _new_account(client, c1, "kuaishou", "a2")
        a3 = _new_account(client, c2, "douyin", "a3")

        cross = client.put("/api/cases/case_demo/publish-targets", json={"account_ids": [a1, a3]})
        assert 400 <= cross.status_code < 500, cross.text  # mixed clients rejected

        ghost = client.put("/api/cases/case_demo/publish-targets", json={"account_ids": [a1, "ghost"]})
        assert 400 <= ghost.status_code < 500, ghost.text  # unknown account rejected

        ok = client.put("/api/cases/case_demo/publish-targets", json={"account_ids": [a1, a2]})
        assert ok.status_code == 200, ok.text
        assert {t["account_id"] for t in ok.json()["items"]} == {a1, a2}

        subset = client.put("/api/cases/case_demo/publish-targets", json={"account_ids": [a1]})
        assert {t["account_id"] for t in subset.json()["items"]} == {a1}
        listed = client.get("/api/cases/case_demo/publish-targets")
        assert {t["account_id"] for t in listed.json()["items"]} == {a1}


def test_delete_account_soft_archives():
    with TestClient(create_app()) as client:
        _login(client)
        client_id = _new_client(client)
        account_id = _new_account(client, client_id, "douyin", "dy")

        deleted = client.delete(f"/api/publish/accounts/{account_id}")
        assert deleted.status_code == 200, deleted.text

        items = client.get(f"/api/publish/accounts?client_id={client_id}").json()["items"]
        assert all(item["id"] != account_id for item in items)


def test_patch_account_archive_clears_session_and_targets():
    with TestClient(create_app()) as client:
        _login(client)
        client_id = _new_client(client)
        account_id = _new_account(client, client_id, "douyin", "dy")
        _complete_login(client, account_id)
        client.put("/api/cases/case_demo/publish-targets", json={"account_ids": [account_id]})

        patched = client.patch(f"/api/publish/accounts/{account_id}", json={"status": "archived"})
        assert patched.status_code == 200, patched.text

        archived = client.get(
            f"/api/publish/accounts?client_id={client_id}&include_archived=true"
        ).json()["items"]
        account = next(item for item in archived if item["id"] == account_id)
        assert account["status"] == "archived"
        assert account["has_session"] is False
        assert account["session_status"] == "expired"
        targets = client.get("/api/cases/case_demo/publish-targets").json()["items"]
        assert all(target["account_id"] != account_id for target in targets)


def test_archive_cancels_logins_registered_during_archive(monkeypatch):
    with TestClient(create_app()) as client:
        _login(client)
        client_id = _new_client(client)
        account_id = _new_account(client, client_id, "douyin", "dy")
        registry = client.app.state.publish_login_registry
        calls = 0
        original_cancel = publish_login.cancel_logins_for_account

        def cancel_then_register(account_id_arg, request):
            nonlocal calls
            calls += 1
            original_cancel(account_id_arg, request)
            if calls == 1:
                repo = MemoryAccountsRepository(client.app.state.repository)
                account = repo.get_account(account_id_arg)
                registry.add(login_id="login_race", account_id=account_id_arg, platform=account.platform)

        monkeypatch.setattr(publish_login, "cancel_logins_for_account", cancel_then_register)

        deleted = client.delete(f"/api/publish/accounts/{account_id}")
        assert deleted.status_code == 200, deleted.text
        assert calls == 2
        assert registry.get("login_race") is None


def test_patch_account_can_clear_platform_uid():
    with TestClient(create_app()) as client:
        _login(client)
        client_id = _new_client(client)
        account_id = _new_account(client, client_id, "douyin", "dy", platform_uid="dy-123")

        patched = client.patch(f"/api/publish/accounts/{account_id}", json={"platform_uid": None})
        assert patched.status_code == 200, patched.text
        assert patched.json()["platform_uid"] is None


def test_patch_account_rename_conflict():
    with TestClient(create_app()) as client:
        _login(client)
        client_id = _new_client(client)
        _new_account(client, client_id, "douyin", "first")
        second = _new_account(client, client_id, "douyin", "second")
        resp = client.patch(f"/api/publish/accounts/{second}", json={"account_name": "first"})
        assert 400 <= resp.status_code < 500, resp.text  # natural-key conflict


def test_set_targets_unknown_case_rejected():
    with TestClient(create_app()) as client:
        _login(client)
        client_id = _new_client(client)
        a1 = _new_account(client, client_id, "douyin", "a1")
        resp = client.put("/api/cases/ghost_case_xyz/publish-targets", json={"account_ids": [a1]})
        assert 400 <= resp.status_code < 500, resp.text


def test_archived_account_removed_from_targets_and_unbindable():
    with TestClient(create_app()) as client:
        _login(client)
        client_id = _new_client(client)
        a1 = _new_account(client, client_id, "douyin", "a1")
        a2 = _new_account(client, client_id, "kuaishou", "a2")
        client.put("/api/cases/case_demo/publish-targets", json={"account_ids": [a1, a2]})

        assert client.delete(f"/api/publish/accounts/{a1}").status_code == 200
        remaining = {
            t["account_id"]
            for t in client.get("/api/cases/case_demo/publish-targets").json()["items"]
        }
        assert a1 not in remaining and a2 in remaining

        rebind = client.put("/api/cases/case_demo/publish-targets", json={"account_ids": [a1, a2]})
        assert 400 <= rebind.status_code < 500, rebind.text  # archived account unbindable


def test_endpoints_require_auth():
    with TestClient(create_app()) as client:
        resp = client.get("/api/publish/clients")
        assert resp.status_code in (401, 403), resp.text
