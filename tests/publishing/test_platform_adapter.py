"""PublishPlatformAdapter port: sandbox behavior + feature-flag adapter selection."""

from __future__ import annotations

from packages.publishing.platform_adapter import (
    BrowserPublishAdapter,
    SANDBOX_ADAPTER_ID,
    PublishPayload,
    SandboxPublishAdapter,
    resolve_adapter_id,
    select_adapter,
)


def test_resolve_adapter_id_defaults_to_sandbox(monkeypatch):
    monkeypatch.delenv("CUTAGENT_PUBLISH_ADAPTER", raising=False)
    assert resolve_adapter_id() == SANDBOX_ADAPTER_ID


def test_resolve_adapter_id_honors_explicit_and_flag(monkeypatch):
    assert resolve_adapter_id("douyin.web") == "douyin.web"
    monkeypatch.setenv("CUTAGENT_PUBLISH_ADAPTER", "douyin.web")
    assert resolve_adapter_id() == "douyin.web"


def test_select_adapter_defaults_to_sandbox(monkeypatch):
    monkeypatch.delenv("CUTAGENT_PUBLISH_ADAPTER", raising=False)
    adapter = select_adapter()
    assert isinstance(adapter, SandboxPublishAdapter)
    assert adapter.adapter_id == SANDBOX_ADAPTER_ID


def test_select_adapter_falls_back_to_sandbox_for_unregistered_id(monkeypatch):
    # No production adapter is registered yet; an unknown id must fall back to the
    # sandbox adapter rather than hitting a non-existent adapter.
    monkeypatch.setenv("CUTAGENT_PUBLISH_ADAPTER", "douyin.web")
    adapter = select_adapter()
    assert isinstance(adapter, SandboxPublishAdapter)


def test_sandbox_adapter_publishes_successfully():
    adapter = SandboxPublishAdapter()
    outcome = adapter.publish(PublishPayload(title="t", platforms=("douyin",)))
    assert outcome.success is True
    assert outcome.adapter_id == SANDBOX_ADAPTER_ID
    assert outcome.scheduled is False


def test_sandbox_adapter_simulates_failure():
    adapter = SandboxPublishAdapter()
    outcome = adapter.publish(PublishPayload(title="t", platforms=("douyin",), simulate_failure=True))
    assert outcome.success is False
    assert outcome.error_message


def test_sandbox_adapter_reports_scheduled():
    from datetime import datetime, timedelta

    adapter = SandboxPublishAdapter()
    outcome = adapter.publish(
        PublishPayload(title="t", platforms=("douyin",), scheduled_at=datetime.now() + timedelta(hours=2))
    )
    assert outcome.success is True
    assert outcome.scheduled is True


def test_sandbox_adapter_probe_accounts_returns_stub_set():
    adapter = SandboxPublishAdapter()
    accounts, available, reason = adapter.probe_accounts(case_name="case")
    assert available is True
    assert reason is None
    assert {a.platform for a in accounts} == {"douyin", "kuaishou", "shipinhao", "xiaohongshu"}


def test_browser_adapter_fails_without_account_session_or_video():
    outcome = BrowserPublishAdapter().publish(PublishPayload(title="t", platforms=("douyin",)))
    assert outcome.success is False
    assert outcome.adapter_id == "browser.playwright"
    assert outcome.error_message
    assert "storage_state_json" in outcome.error_message
