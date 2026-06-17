"""Playwright browser-session driver (publishing center) — UNVERIFIED.

Drives a real browser (intended for the Mac Mini publishing host) to perform QR
login on 抖音/视频号/快手/小红书 creator backends and to validate persisted sessions.

UNVERIFIED: the per-platform URLs/selectors (``platforms.py``) and login-success
detection have NOT been validated against the live platforms and WILL need tuning on
real accounts / each platform redesign. It fails LOUDLY (never fabricates success)
when Playwright or its browser is unavailable. Async Playwright work is bridged to
this sync driver interface via a dedicated thread + fresh event loop, so it never
touches the caller's loop. Browser sessions are held open between ``begin_login`` and
``poll_login`` until the scan completes or ``close`` is called.

This driver is only constructed when ``CUTAGENT_PUBLISH_BROWSER_DRIVER=playwright``;
the sandbox default never imports it.
"""

from __future__ import annotations

import asyncio
import base64
import json
import threading
from typing import Any

from packages.core.storage.repository import new_id
from packages.publishing.browser.driver import (
    PLAYWRIGHT_BROWSER_DRIVER,
    LoginHandle,
    LoginPollResult,
    SessionCheck,
    browser_unavailable,
)
from packages.publishing.browser.platforms import platform_login

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
)


def _run_async(coro: Any) -> Any:
    """Run a coroutine to completion on a fresh loop in a dedicated thread.

    Keeps the async Playwright work off the caller's event loop entirely, so the sync
    driver interface is safe to call from FastAPI's threadpool routes.
    """
    box: dict[str, Any] = {}

    def runner() -> None:
        loop = asyncio.new_event_loop()
        try:
            box["value"] = loop.run_until_complete(coro)
        except BaseException as exc:  # noqa: BLE001 - re-raised to the caller below
            box["error"] = exc
        finally:
            loop.close()

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box["value"]


class PlaywrightBrowserDriver:
    """UNVERIFIED real-browser driver. Held as a singleton on ``app.state``."""

    driver_id: str = PLAYWRIGHT_BROWSER_DRIVER

    def __init__(self, *, headless: bool = True) -> None:
        self._headless = headless
        # login_token -> (playwright, browser, context, page, platform_login)
        self._sessions: dict[str, tuple[Any, Any, Any, Any, Any]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _async_playwright():
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:  # pragma: no cover - optional/runtime dep on the host
            raise browser_unavailable(f"Playwright is not available: {exc}") from exc
        return async_playwright

    def begin_login(self, platform: str) -> LoginHandle:
        try:
            login = platform_login(platform)
        except KeyError as exc:
            raise browser_unavailable(f"Unsupported platform for browser login: {platform}") from exc
        async_playwright = self._async_playwright()
        token = new_id("login")

        async def _begin() -> str:
            pw = await async_playwright().start()
            try:
                browser = await pw.chromium.launch(headless=self._headless)
                context = await browser.new_context(user_agent=MOBILE_UA)
                page = await context.new_page()
                await page.goto(login.login_url, timeout=60000)
                await page.wait_for_timeout(2500)
                element = await page.query_selector(login.qr_selector)
                if element is None:
                    await pw.stop()
                    raise browser_unavailable("Login QR element not found on the login page.")
                png = await element.screenshot()
                with self._lock:
                    self._sessions[token] = (pw, browser, context, page, login)
                return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
            except Exception:
                await pw.stop()
                raise

        return LoginHandle(login_token=token, qr_image=_run_async(_begin()))

    def poll_login(self, login_token: str) -> LoginPollResult:
        with self._lock:
            entry = self._sessions.get(login_token)
        if entry is None:
            return LoginPollResult(status="failed", detail="unknown or closed login session")
        _pw, _browser, context, page, login = entry

        async def _poll() -> LoginPollResult:
            # UNVERIFIED heuristic: a successful scan lands on the creator backend whose
            # URL carries ``logged_in_signal`` (login pages do not).
            if login.logged_in_signal not in page.url:
                return LoginPollResult(status="pending")
            state = await context.storage_state()
            return LoginPollResult(status="success", storage_state_json=json.dumps(state))

        return _run_async(_poll())

    def validate_session(self, platform: str, storage_state_json: str) -> SessionCheck:
        try:
            login = platform_login(platform)
        except KeyError as exc:
            raise browser_unavailable(f"Unsupported platform: {platform}") from exc
        async_playwright = self._async_playwright()

        async def _validate() -> SessionCheck:
            pw = await async_playwright().start()
            try:
                browser = await pw.chromium.launch(headless=self._headless)
                context = await browser.new_context(
                    user_agent=MOBILE_UA, storage_state=json.loads(storage_state_json)
                )
                page = await context.new_page()
                await page.goto(login.creator_home_url, timeout=60000)
                await page.wait_for_timeout(2000)
                active = login.logged_in_signal in page.url
                await browser.close()
                return SessionCheck(active=active)
            finally:
                await pw.stop()

        return _run_async(_validate())

    def close(self, login_token: str) -> None:
        with self._lock:
            entry = self._sessions.pop(login_token, None)
        if entry is None:
            return
        pw, browser, _context, _page, _login = entry

        async def _close() -> None:
            try:
                await browser.close()
            finally:
                await pw.stop()

        try:
            _run_async(_close())
        except Exception:  # pragma: no cover - cleanup is best-effort
            pass
