"""Accounts repository + session lifecycle (memory backend, no HTTP)."""

from __future__ import annotations

import pytest

from packages.core.contracts.state_machines import assert_transition
from packages.core.storage.repository import Repository
from packages.core.storage.secret_store import LocalSecretStore
from packages.core.workflow import NodeExecutionError
from packages.publishing import MemoryAccountsRepository
from packages.publishing.account_sessions import clear_account_session, store_account_session


def _repo() -> MemoryAccountsRepository:
    return MemoryAccountsRepository(Repository())


def test_client_account_crud_roundtrip():
    repo = _repo()
    client = repo.create_client(name="ACME", remark="vip")
    assert client.status == "active"
    assert repo.client_exists(client.id)

    account = repo.create_account(client_id=client.id, platform="douyin", account_name="acme-dy")
    assert account.client_id == client.id
    assert account.has_session is False
    assert account.session_status == "never_logged_in"

    assert [a.id for a in repo.list_accounts(client_id=client.id)] == [account.id]
    assert repo.list_accounts(client_id=client.id, platform="kuaishou") == []


def test_natural_key_lookup():
    repo = _repo()
    client = repo.create_client(name="ACME")
    repo.create_account(client_id=client.id, platform="douyin", account_name="a")
    assert (
        repo.find_account_by_natural_key(client_id=client.id, platform="douyin", account_name="a")
        is not None
    )
    assert (
        repo.find_account_by_natural_key(client_id=client.id, platform="douyin", account_name="b")
        is None
    )


def test_store_session_writes_secret_and_sets_status(tmp_path):
    repo = _repo()
    store = LocalSecretStore(root=tmp_path)
    client = repo.create_client(name="ACME")
    account = repo.create_account(client_id=client.id, platform="douyin", account_name="a")

    updated = store_account_session(repo, store, account.id, '{"cookies": ["v1"]}')
    assert updated is not None
    assert updated.session_status == "active"
    assert updated.has_session is True
    assert updated.last_validated_at is not None

    ref = repo.get_account_session_ref(account.id)
    assert ref is not None
    assert store.get(ref) == '{"cookies": ["v1"]}'


def test_replace_session_disables_old_secret(tmp_path):
    repo = _repo()
    store = LocalSecretStore(root=tmp_path)
    client = repo.create_client(name="ACME")
    account = repo.create_account(client_id=client.id, platform="douyin", account_name="a")

    store_account_session(repo, store, account.id, "session-1")
    old_ref = repo.get_account_session_ref(account.id)
    store_account_session(repo, store, account.id, "session-2")
    new_ref = repo.get_account_session_ref(account.id)

    assert new_ref != old_ref
    assert store.get(old_ref) is None  # prior secret disabled — no orphan
    assert store.get(new_ref) == "session-2"


def test_clear_session_disables_secret_and_expires(tmp_path):
    repo = _repo()
    store = LocalSecretStore(root=tmp_path)
    client = repo.create_client(name="ACME")
    account = repo.create_account(client_id=client.id, platform="douyin", account_name="a")
    store_account_session(repo, store, account.id, "session-1")
    ref = repo.get_account_session_ref(account.id)

    cleared = clear_account_session(repo, store, account.id)
    assert cleared.session_status == "expired"
    assert cleared.has_session is False
    assert store.get(ref) is None
    assert repo.get_account_session_ref(account.id) is None


def test_archive_account_blocks_late_session_store(tmp_path):
    repo = _repo()
    store = LocalSecretStore(root=tmp_path)
    client = repo.create_client(name="ACME")
    account = repo.create_account(client_id=client.id, platform="douyin", account_name="a")
    store_account_session(repo, store, account.id, "session-1")
    old_ref = repo.get_account_session_ref(account.id)

    archived, archived_ref = repo.archive_account(account.id)
    assert archived is not None
    assert archived.status == "archived"
    assert archived.session_status == "expired"
    assert archived.has_session is False
    assert archived_ref == old_ref
    assert repo.get_account_session_ref(account.id) is None

    late = store_account_session(repo, store, account.id, "late-session")
    assert late is None
    assert repo.get_account_session_ref(account.id) is None
    assert repo.get_account(account.id).has_session is False


def test_targets_replace_is_idempotent_and_hydrated():
    repo = _repo()
    client = repo.create_client(name="ACME")
    a1 = repo.create_account(client_id=client.id, platform="douyin", account_name="a1")
    a2 = repo.create_account(client_id=client.id, platform="kuaishou", account_name="a2")

    repo.set_targets("case_x", [a1.id, a2.id])
    targets = {t.account_id: t for t in repo.list_targets("case_x")}
    assert set(targets) == {a1.id, a2.id}
    assert targets[a1.id].platform == "douyin"
    assert targets[a1.id].client_id == client.id

    repo.set_targets("case_x", [a1.id])  # idempotent replace to subset
    assert {t.account_id for t in repo.list_targets("case_x")} == {a1.id}


def test_publish_session_state_machine_rejects_illegal():
    assert_transition("publish_session", "never_logged_in", "active")
    assert_transition("publish_session", "active", "expired")
    assert_transition("publish_session", "expired", "active")
    assert_transition("publish_session", "active", "active")  # idempotent refresh
    with pytest.raises(NodeExecutionError):
        assert_transition("publish_session", "never_logged_in", "expired")


def test_archived_account_excluded_from_client_map_and_targets_cleaned():
    repo = _repo()
    client = repo.create_client(name="ACME")
    a1 = repo.create_account(client_id=client.id, platform="douyin", account_name="a1")
    repo.set_targets("case_x", [a1.id])
    assert {t.account_id for t in repo.list_targets("case_x")} == {a1.id}

    repo.patch_account(a1.id, status="archived")
    repo.delete_targets_for_account(a1.id)
    assert repo.list_targets("case_x") == []
    assert repo.accounts_client_map([a1.id]) == {}  # archived account can't be re-bound
