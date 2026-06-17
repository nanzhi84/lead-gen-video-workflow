"""Browser session driver (sandbox) + login registry unit tests."""

from __future__ import annotations

from datetime import timedelta

from packages.publishing.browser import (
    SANDBOX_BROWSER_DRIVER,
    LoginSession,
    PublishLoginRegistry,
    SandboxBrowserDriver,
    resolve_browser_driver_id,
    select_browser_driver,
)


def test_select_driver_defaults_to_sandbox(monkeypatch):
    monkeypatch.delenv("CUTAGENT_PUBLISH_BROWSER_DRIVER", raising=False)
    assert resolve_browser_driver_id() == SANDBOX_BROWSER_DRIVER
    assert isinstance(select_browser_driver(), SandboxBrowserDriver)


def test_resolve_driver_honors_explicit_and_env(monkeypatch):
    assert resolve_browser_driver_id("playwright") == "playwright"
    monkeypatch.setenv("CUTAGENT_PUBLISH_BROWSER_DRIVER", "playwright")
    assert resolve_browser_driver_id() == "playwright"


def test_sandbox_driver_login_flow():
    driver = SandboxBrowserDriver()
    handle = driver.begin_login("douyin")
    assert handle.qr_image.startswith("data:image/")
    assert handle.login_token
    assert driver.poll_login(handle.login_token).status == "pending"
    result = driver.poll_login(handle.login_token)
    assert result.status == "success"
    assert result.storage_state_json is not None
    driver.close(handle.login_token)
    assert driver.poll_login(handle.login_token).status == "failed"  # closed/unknown


def test_sandbox_driver_validate_active():
    assert SandboxBrowserDriver().validate_session("douyin", "{}").active is True


def test_login_registry_lifecycle_and_sweep():
    registry = PublishLoginRegistry(ttl=timedelta(seconds=-1))  # everything immediately expired
    session = registry.add(login_id="login_1", account_id="acct_1", platform="douyin")
    assert isinstance(session, LoginSession)
    assert registry.get("login_1").status == "pending"
    registry.update("login_1", status="active")
    assert registry.get("login_1").status == "active"
    assert "login_1" in registry.sweep_expired()
    assert registry.get("login_1") is None
