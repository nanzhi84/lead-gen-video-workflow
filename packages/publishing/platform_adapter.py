"""PublishPlatformAdapter port + adapters.

The publish subsystem talks to platforms through the ``PublishPlatformAdapter``
port. ``SandboxPublishAdapter`` (``adapter_id="sandbox.publish"``) is the
default implementation: an in-process state-machine adapter that walks the
publish_item/publish_batch lifecycle and records ``PublishAttempt`` rows without
touching any external platform.

``BrowserPublishAdapter`` (``adapter_id="browser.playwright"``) registers
best-effort browser upload paths for 抖音/视频号/快手/小红书, but remains
UNVERIFIED and returns failure until live success detection exists. ``select_adapter``
chooses the adapter from an explicit override, then the ``CUTAGENT_PUBLISH_ADAPTER``
feature flag, defaulting to sandbox so production stays a safe no-op.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from packages.core.contracts import PlatformAccount

SANDBOX_ADAPTER_ID = "sandbox.publish"


@dataclass(frozen=True)
class PublishPayload:
    """Platform-agnostic publish payload assembled from a publish item."""

    title: str
    description: str = ""
    platforms: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    location: str | None = None
    account_group: str | None = None
    account_id: str | None = None
    account_name: str | None = None
    storage_state_json: str | None = None
    video_path: str | None = None
    case_name: str | None = None
    scheduled_at: datetime | None = None
    video_uri: str | None = None
    cover_uri: str | None = None
    manual_review: bool = False
    # Sandbox-only deterministic failure switch (parity with the existing
    # simulate_publish_failure submit knob); never used by real adapters.
    simulate_failure: bool = False


@dataclass(frozen=True)
class PublishOutcome:
    success: bool
    adapter_id: str
    external_task_id: str | None = None
    results: list[dict] = field(default_factory=list)
    error_message: str | None = None
    scheduled: bool = False


class PublishPlatformAdapter(Protocol):
    adapter_id: str

    def probe_accounts(
        self,
        *,
        account_group: str | None = None,
        case_name: str | None = None,
    ) -> tuple[list[PlatformAccount], bool, str | None]:
        """Return ``(accounts, available, unavailable_reason)``."""
        ...

    def publish(self, payload: PublishPayload) -> PublishOutcome:
        ...


@dataclass
class SandboxPublishAdapter:
    """In-process state-machine adapter. Records attempts; never touches a
    platform. Returns deterministic outcomes (honouring ``simulate_failure``)."""

    adapter_id: str = SANDBOX_ADAPTER_ID

    def probe_accounts(
        self,
        *,
        account_group: str | None = None,
        case_name: str | None = None,
    ) -> tuple[list[PlatformAccount], bool, str | None]:
        # A deterministic stub account set so the platform-accounts endpoint and
        # account-group matching are exercisable without the live app.
        accounts = [
            PlatformAccount(
                uid=f"sandbox-{platform}",
                platform=platform,
                nickname=f"沙盒账号-{platform}",
                account_group=account_group,
                is_login=True,
            )
            for platform in ("douyin", "kuaishou", "shipinhao", "xiaohongshu")
        ]
        return accounts, True, None

    def publish(self, payload: PublishPayload) -> PublishOutcome:
        if payload.manual_review:
            return PublishOutcome(
                success=True,
                adapter_id=self.adapter_id,
                results=[{"platform": p, "manual_review_ready": True} for p in payload.platforms],
            )
        if payload.simulate_failure:
            return PublishOutcome(
                success=False,
                adapter_id=self.adapter_id,
                results=[{"platform": p, "success": False} for p in payload.platforms],
                error_message="Sandbox publish adapter simulated a failed publish.",
            )
        scheduled = payload.scheduled_at is not None
        return PublishOutcome(
            success=True,
            adapter_id=self.adapter_id,
            results=[{"platform": p, "success": True, "scheduled": scheduled} for p in payload.platforms],
            scheduled=scheduled,
        )


@dataclass
class BrowserPublishAdapter:
    """UNVERIFIED Playwright browser upload adapter.

    This adapter is intentionally conservative: it dispatches to platform-specific
    upload paths and returns failure unless all account/session/video inputs are
    present. The DOM automation has not been verified against the live platforms,
    so it does not fabricate success after best-effort browser interactions.
    """

    adapter_id: str = "browser.playwright"

    def probe_accounts(
        self,
        *,
        account_group: str | None = None,
        case_name: str | None = None,
    ) -> tuple[list[PlatformAccount], bool, str | None]:
        return [], False, "Browser publish adapter is UNVERIFIED and does not probe accounts."

    def publish(self, payload: PublishPayload) -> PublishOutcome:
        missing = [
            field_name
            for field_name, value in (
                ("account_id", payload.account_id),
                ("storage_state_json", payload.storage_state_json),
                ("video_path", payload.video_path),
            )
            if not value
        ]
        if missing:
            return self._failure(
                payload,
                f"publish.browser_unavailable: missing {', '.join(missing)}.",
            )
        platform = payload.platforms[0] if payload.platforms else None
        # Dispatch to supported browser handlers; each handler still returns
        # failure until success detection exists.
        handlers = {
            "douyin": self._publish_douyin,
            "shipinhao": self._publish_shipinhao,
            "kuaishou": self._publish_kuaishou,
            "xiaohongshu": self._publish_xiaohongshu,
        }
        handler = handlers.get(platform)
        if handler is None:
            return self._failure(
                payload,
                f"publish.browser_unavailable: platform {platform or '<missing>'} not yet supported.",
            )
        if not Path(payload.video_path).exists():
            return self._failure(payload, "publish.browser_unavailable: video_path does not exist.")

        try:
            from packages.publishing.browser.playwright_driver import _run_async

            return _run_async(handler(payload))
        except Exception as exc:  # noqa: BLE001 - adapter boundary must fail loudly, not crash submit.
            return self._failure(payload, f"publish.browser_unavailable: {exc}")

    def _failure(self, payload: PublishPayload, message: str) -> PublishOutcome:
        platform = payload.platforms[0] if payload.platforms else None
        return PublishOutcome(
            success=False,
            adapter_id=self.adapter_id,
            results=[
                {
                    "platform": platform,
                    "account_id": payload.account_id,
                    "success": False,
                    "error": message,
                }
            ],
            error_message=message,
        )

    async def _publish_douyin(self, payload: PublishPayload) -> PublishOutcome:
        """UNVERIFIED best-effort Douyin upload; success detection is absent."""
        import json

        from playwright.async_api import async_playwright

        from packages.publishing.browser.playwright_driver import DESKTOP_UA, _launch_kwargs

        storage_state = json.loads(payload.storage_state_json or "{}")
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(**_launch_kwargs(headless=True))
            try:
                context = await browser.new_context(
                    user_agent=DESKTOP_UA,
                    storage_state=storage_state,
                )
                page = await context.new_page()
                await page.goto(
                    "https://creator.douyin.com/creator-micro/content/upload",
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                await page.locator("input[type='file']").first.set_input_files(
                    payload.video_path,
                    timeout=60000,
                )
                await self._fill_first_available(
                    page,
                    ("input[placeholder*='标题']", "textarea[placeholder*='标题']"),
                    payload.title,
                )
                if payload.description:
                    await self._fill_first_available(
                        page,
                        ("textarea[placeholder*='描述']", "textarea"),
                        payload.description,
                    )
            finally:
                await browser.close()
        return self._failure(
            payload,
            "publish.browser_unavailable: Douyin upload adapter is UNVERIFIED; "
            "success detection is not implemented; final publish click was skipped.",
        )

    async def _publish_shipinhao(self, payload: PublishPayload) -> PublishOutcome:
        """UNVERIFIED best-effort Shipinhao upload; success detection is absent."""
        import json

        from playwright.async_api import async_playwright

        from packages.publishing.browser.playwright_driver import DESKTOP_UA, _launch_kwargs

        storage_state = json.loads(payload.storage_state_json or "{}")
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(**_launch_kwargs(headless=True))
            try:
                context = await browser.new_context(
                    user_agent=DESKTOP_UA,
                    storage_state=storage_state,
                )
                page = await context.new_page()
                await page.goto(
                    "https://channels.weixin.qq.com/platform/post/create",
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                await page.locator("input[type='file']").first.set_input_files(
                    payload.video_path,
                    timeout=60000,
                )
                await self._fill_first_available(
                    page,
                    ("input[placeholder*='标题']", "textarea"),
                    payload.title,
                )
                if payload.description:
                    await self._fill_first_available(
                        page,
                        ("textarea[placeholder*='描述']", "textarea"),
                        payload.description,
                    )
            finally:
                await browser.close()
        return self._failure(
            payload,
            "publish.browser_unavailable: Shipinhao upload adapter is UNVERIFIED; "
            "success detection is not implemented; final publish click was skipped.",
        )

    async def _publish_kuaishou(self, payload: PublishPayload) -> PublishOutcome:
        """UNVERIFIED best-effort Kuaishou upload; success detection is absent."""
        import json

        from playwright.async_api import async_playwright

        from packages.publishing.browser.playwright_driver import DESKTOP_UA, _launch_kwargs

        storage_state = json.loads(payload.storage_state_json or "{}")
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(**_launch_kwargs(headless=True))
            try:
                context = await browser.new_context(
                    user_agent=DESKTOP_UA,
                    storage_state=storage_state,
                )
                page = await context.new_page()
                await page.goto(
                    "https://cp.kuaishou.com/article/publish/video",
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                await page.locator("input[type='file']").first.set_input_files(
                    payload.video_path,
                    timeout=60000,
                )
                if payload.description:
                    await self._fill_first_available(
                        page,
                        ("textarea[placeholder*='描述']", "textarea"),
                        payload.description,
                    )
            finally:
                await browser.close()
        return self._failure(
            payload,
            "publish.browser_unavailable: Kuaishou upload adapter is UNVERIFIED; "
            "success detection is not implemented; final publish click was skipped.",
        )

    async def _publish_xiaohongshu(self, payload: PublishPayload) -> PublishOutcome:
        """UNVERIFIED best-effort Xiaohongshu upload; success detection is absent."""
        import json

        from playwright.async_api import async_playwright

        from packages.publishing.browser.playwright_driver import DESKTOP_UA, _launch_kwargs

        storage_state = json.loads(payload.storage_state_json or "{}")
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(**_launch_kwargs(headless=True))
            try:
                context = await browser.new_context(
                    user_agent=DESKTOP_UA,
                    storage_state=storage_state,
                )
                page = await context.new_page()
                await page.goto(
                    "https://creator.xiaohongshu.com/publish/publish",
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                await page.locator("input[type='file']").first.set_input_files(
                    payload.video_path,
                    timeout=60000,
                )
                await self._fill_first_available(
                    page,
                    ("input[placeholder*='标题']",),
                    payload.title,
                )
                if payload.description:
                    await self._fill_first_available(
                        page,
                        ("textarea[placeholder*='描述']", "textarea"),
                        payload.description,
                    )
            finally:
                await browser.close()
        return self._failure(
            payload,
            "publish.browser_unavailable: Xiaohongshu upload adapter is UNVERIFIED; "
            "success detection is not implemented; final publish click was skipped.",
        )

    async def _fill_first_available(self, page: Any, selectors: tuple[str, ...], value: str) -> None:
        for selector in selectors:
            locator = page.locator(selector).first
            if await locator.count() == 0:
                continue
            await locator.fill(value, timeout=10000)
            return

# Registered publish adapters by id. Browser automation remains opt-in through
# CUTAGENT_PUBLISH_ADAPTER.
_PUBLISH_ADAPTERS: dict[str, Callable[[], PublishPlatformAdapter]] = {
    SANDBOX_ADAPTER_ID: SandboxPublishAdapter,
    "browser.playwright": BrowserPublishAdapter,
}


def resolve_adapter_id(explicit: str | None = None) -> str:
    """Resolve the publish adapter id: explicit override > feature flag > sandbox.

    ``CUTAGENT_PUBLISH_ADAPTER`` selects a production adapter once one is wired.
    Default is the sandbox adapter so production publishing stays a safe, explicit
    no-op until a real platform adapter is registered.
    """
    if explicit:
        return explicit
    return os.getenv("CUTAGENT_PUBLISH_ADAPTER") or SANDBOX_ADAPTER_ID


def select_adapter(explicit: str | None = None) -> PublishPlatformAdapter:
    """Select a publish adapter by id, defaulting to sandbox.

    Unknown/unimplemented ids fall back to the sandbox adapter so publishing never
    silently hits a non-existent adapter.
    """
    factory = _PUBLISH_ADAPTERS.get(resolve_adapter_id(explicit), SandboxPublishAdapter)
    return factory()
