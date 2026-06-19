"""Browser-session driver port for publish-account QR login (publishing center).

``SandboxBrowserDriver`` (deterministic, no real browser) is the only driver until
the 小V猫 CDP driver lands (PR4); it is the tested default. ``select_browser_driver``
returns it regardless of override/env for now.

The driver is **stateful**: ``begin_login`` opens a browser session keyed by
``login_token`` that stays alive until the operator scans the QR (``poll_login``
returns ``success``) or it is ``close``d (poll terminal / TTL sweep). Drivers are
created ONCE and held on ``app.state`` — never per-request — so begin/poll share state.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, Protocol

from packages.core.contracts import ErrorCode
from packages.core.storage.repository import new_id
from packages.core.workflow import NodeExecutionError

SANDBOX_BROWSER_DRIVER = "sandbox"


def browser_unavailable(message: str) -> NodeExecutionError:
    """Explicit failure for an unavailable/failed browser backend (never fabricate)."""
    return NodeExecutionError(ErrorCode.publish_browser_unavailable, message)


@dataclass(frozen=True)
class LoginHandle:
    login_token: str
    qr_image: str  # data-url of the login QR — a login credential; never log/cache it


@dataclass(frozen=True)
class LoginPollResult:
    status: Literal["pending", "success", "failed"]
    storage_state_json: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class SessionCheck:
    active: bool
    detail: str | None = None


class BrowserSessionDriver(Protocol):
    driver_id: str

    def begin_login(self, platform: str) -> LoginHandle: ...
    def poll_login(self, login_token: str) -> LoginPollResult: ...
    def validate_session(self, platform: str, storage_state_json: str) -> SessionCheck: ...
    def close(self, login_token: str) -> None: ...


# A 1x1 transparent PNG placeholder — the sandbox "QR" (no real login involved).
_SANDBOX_QR_PLACEHOLDER = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


class SandboxBrowserDriver:
    """Deterministic no-browser driver: ``begin`` returns a placeholder QR; ``poll``
    returns ``pending`` once then ``success`` with a synthetic storage_state;
    ``validate`` is always active. The default driver and the only one tests use."""

    driver_id: str = SANDBOX_BROWSER_DRIVER

    def __init__(self) -> None:
        self._polls: dict[str, int] = {}

    def begin_login(self, platform: str) -> LoginHandle:
        token = new_id("login")
        self._polls[token] = 0
        return LoginHandle(login_token=token, qr_image=_SANDBOX_QR_PLACEHOLDER)

    def poll_login(self, login_token: str) -> LoginPollResult:
        if login_token not in self._polls:
            return LoginPollResult(status="failed", detail="unknown login token")
        self._polls[login_token] += 1
        if self._polls[login_token] < 2:
            return LoginPollResult(status="pending")
        return LoginPollResult(
            status="success",
            storage_state_json='{"cookies": [], "origins": [], "_sandbox": true}',
        )

    def validate_session(self, platform: str, storage_state_json: str) -> SessionCheck:
        return SessionCheck(active=True)

    def close(self, login_token: str) -> None:
        self._polls.pop(login_token, None)


def resolve_browser_driver_id(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    return os.getenv("CUTAGENT_PUBLISH_BROWSER_DRIVER") or SANDBOX_BROWSER_DRIVER


def select_browser_driver(explicit: str | None = None) -> BrowserSessionDriver:
    """Select a browser driver. Only the sandbox driver exists until the 小V猫 CDP
    driver lands (PR4); any explicit/env selection degrades to the sandbox driver."""
    return SandboxBrowserDriver()
