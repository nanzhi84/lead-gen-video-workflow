"""PublishPlatformAdapter port: sandbox behavior + feature-flag adapter selection."""

from __future__ import annotations

import asyncio
import sys
import types

import pytest

from packages.publishing.browser import playwright_driver
from packages.publishing.platform_adapter import (
    BrowserPublishAdapter,
    SANDBOX_ADAPTER_ID,
    PublishOutcome,
    PublishPayload,
    SandboxPublishAdapter,
    resolve_adapter_id,
    select_adapter,
)


class _FakeLocator:
    def __init__(self, *, role_name: str | None = None):
        self.first = self
        self.role_name = role_name

    async def count(self):
        return 1

    async def fill(self, _value, *, timeout):
        return None

    async def set_input_files(self, _path, *, timeout):
        return None

    async def click(self, *, timeout):
        raise AssertionError(f"unexpected final publish click: {self.role_name}")


class _FakePage:
    def locator(self, _selector):
        return _FakeLocator()

    def get_by_role(self, _role, *, name):
        return _FakeLocator(role_name=name)

    async def goto(self, *_args, **_kwargs):
        return None


class _FakeContext:
    async def new_page(self):
        return _FakePage()


class _FakeBrowser:
    async def new_context(self, **_kwargs):
        return _FakeContext()

    async def close(self):
        return None


class _FakeChromium:
    async def launch(self, **_kwargs):
        return _FakeBrowser()


class _FakeAsyncPlaywright:
    async def __aenter__(self):
        return types.SimpleNamespace(chromium=_FakeChromium())

    async def __aexit__(self, *_args):
        return False


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


@pytest.mark.parametrize("platform", ["shipinhao", "kuaishou", "xiaohongshu"])
def test_browser_adapter_fails_without_session_or_video_for_supported_platforms(platform):
    outcome = BrowserPublishAdapter().publish(
        PublishPayload(title="t", platforms=(platform,), account_id="account")
    )
    assert outcome.success is False
    assert outcome.adapter_id == "browser.playwright"
    assert outcome.error_message
    assert "storage_state_json" in outcome.error_message
    assert "video_path" in outcome.error_message


@pytest.mark.parametrize(
    ("platform", "method_name"),
    [
        ("shipinhao", "_publish_shipinhao"),
        ("kuaishou", "_publish_kuaishou"),
        ("xiaohongshu", "_publish_xiaohongshu"),
    ],
)
def test_browser_adapter_dispatches_supported_browser_platforms(
    monkeypatch,
    tmp_path,
    platform,
    method_name,
):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake video")
    adapter = BrowserPublishAdapter()
    seen: dict[str, str] = {}

    async def fake_publish(payload: PublishPayload) -> PublishOutcome:
        seen["platform"] = payload.platforms[0]
        return PublishOutcome(
            success=False,
            adapter_id=adapter.adapter_id,
            error_message=f"{platform} handler",
        )

    monkeypatch.setattr(adapter, method_name, fake_publish, raising=False)
    monkeypatch.setattr(playwright_driver, "_run_async", lambda coro: asyncio.run(coro))

    outcome = adapter.publish(
        PublishPayload(
            title="t",
            platforms=(platform,),
            account_id="account",
            storage_state_json="{}",
            video_path=str(video),
        )
    )

    assert seen == {"platform": platform}
    assert outcome.error_message == f"{platform} handler"


@pytest.mark.parametrize(
    ("platform", "method_name"),
    [
        ("douyin", "_publish_douyin"),
        ("shipinhao", "_publish_shipinhao"),
        ("kuaishou", "_publish_kuaishou"),
        ("xiaohongshu", "_publish_xiaohongshu"),
    ],
)
def test_browser_adapter_unverified_handlers_do_not_click_final_publish(
    monkeypatch,
    tmp_path,
    platform,
    method_name,
):
    fake_async_api = types.SimpleNamespace(async_playwright=lambda: _FakeAsyncPlaywright())
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_async_api)
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake video")

    handler = getattr(BrowserPublishAdapter(), method_name)
    outcome = asyncio.run(
        handler(
            PublishPayload(
                title="t",
                description="d",
                platforms=(platform,),
                account_id="account",
                storage_state_json="{}",
                video_path=str(video),
            )
        )
    )

    assert outcome.success is False
    assert outcome.error_message
    assert "success detection is not implemented" in outcome.error_message


@pytest.mark.parametrize("platforms", [("unknown",), ()])
def test_browser_adapter_fails_unknown_or_missing_platform_without_browser(tmp_path, platforms):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake video")

    outcome = BrowserPublishAdapter().publish(
        PublishPayload(
            title="t",
            platforms=platforms,
            account_id="account",
            storage_state_json="{}",
            video_path=str(video),
        )
    )

    assert outcome.success is False
    assert outcome.error_message
    assert "not yet supported" in outcome.error_message
