"""PublishPlatformAdapter port + adapters.

The publish subsystem talks to platforms through the ``PublishPlatformAdapter``
port. ``SandboxPublishAdapter`` (``adapter_id="sandbox.publish"``) is the
default implementation: an in-process state-machine adapter that walks the
publish_item/publish_batch lifecycle and records ``PublishAttempt`` rows without
touching any external platform.

``select_adapter`` chooses the adapter from an explicit override, then the
``CUTAGENT_PUBLISH_ADAPTER`` feature flag, defaulting to the 小V猫 CDP adapter.
小V猫/CDP failures are explicit adapter failures, never fabricated successes.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from packages.core.config.settings import build_publishing_settings
from packages.core.contracts import PlatformAccount

SANDBOX_ADAPTER_ID = "sandbox.publish"

# 小V猫 CDP adapter constants. ``*_KEY_MAP`` maps a generic platform id to the
# platform key 小V猫 exposes via ``CatBridge``; ``*_NAME_MAP`` to its Chinese name.
# Only the 4 supported platforms (no bilibili) — see migration spec decision 4.
XIAOVMAO_ADAPTER_ID = "xiaovmao.cdp"
XIAOVMAO_PLATFORM_KEY_MAP = {
    "douyin": "Douyin",
    "kuaishou": "KuaiShou",
    "shipinhao": "Channels",
    "xiaohongshu": "XiaoHongShu",
}
XIAOVMAO_PLATFORM_NAME_MAP = {
    "douyin": "抖音",
    "kuaishou": "快手",
    "shipinhao": "视频号",
    "xiaohongshu": "小红书",
}


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
    account_uid: str | None = None  # the exact 小V猫 account uid (xiaovmao_uid) to target
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
class XiaoVmaoPublishAdapter:
    """经 CDP 驱动小V猫桌面端发布（``adapter_id="xiaovmao.cdp"``）。

    账号经小V猫的 ``CatBridge`` 实时读取，发布把成片+文案注入小V猫的发布表单，
    由小V猫去发各平台。CDP host/port 经 ``CUTAGENT_XIAOVMAO_CDP_HOST`` /
    ``CUTAGENT_XIAOVMAO_CDP_PORT`` 配置（默认 ``127.0.0.1:9222``，与小V猫同机）。
    小V猫不可达时**显式失败、绝不伪造成功**。
    """

    adapter_id: str = XIAOVMAO_ADAPTER_ID

    def _host_port(self) -> tuple[str, int]:
        publishing = build_publishing_settings()
        return publishing.xiaovmao_cdp_host, publishing.xiaovmao_cdp_port

    def probe_accounts(
        self,
        *,
        account_group: str | None = None,
        case_name: str | None = None,
    ) -> tuple[list[PlatformAccount], bool, str | None]:
        from packages.publishing.connectors.xiaovmao_cdp import probe_xiaovmao_accounts

        host, port = self._host_port()
        return probe_xiaovmao_accounts(
            host=host, port=port, account_group=account_group, case_name=case_name
        )

    def publish(self, payload: PublishPayload) -> PublishOutcome:
        from packages.publishing.connectors.xiaovmao_cdp import publish_via_xiaovmao

        try:
            host, port = self._host_port()
            return publish_via_xiaovmao(payload, host=host, port=port)
        except Exception as exc:
            # 任何 CDP/小V猫错误（不可达、会话断连、JS 异常等）都降级为诚实失败，
            # 绝不伪造成功，也不让异常冒泡 crash 发布流水线。
            results = [
                {"platform": platform, "success": False, "error": str(exc)}
                for platform in payload.platforms
            ] or [{"success": False, "error": str(exc)}]
            return PublishOutcome(
                success=False,
                adapter_id=self.adapter_id,
                results=results,
                error_message=str(exc),
            )


# Registered publish adapters by id. ``xiaovmao.cdp`` drives the 小V猫 desktop app
# over CDP; sandbox remains available for explicit tests/dry integrations.
_PUBLISH_ADAPTERS: dict[str, Callable[[], PublishPlatformAdapter]] = {
    SANDBOX_ADAPTER_ID: SandboxPublishAdapter,
    XIAOVMAO_ADAPTER_ID: XiaoVmaoPublishAdapter,
}


def resolve_adapter_id(explicit: str | None = None) -> str:
    """Resolve the publish adapter id: explicit override > feature flag > 小V猫 CDP.

    ``CUTAGENT_PUBLISH_ADAPTER=sandbox.publish`` remains available for tests and
    local dry integrations. The production default is the 小V猫 CDP adapter; when
    小V猫 is unavailable it returns an explicit failed outcome.
    """
    if explicit:
        return explicit
    return os.getenv("CUTAGENT_PUBLISH_ADAPTER") or XIAOVMAO_ADAPTER_ID


@dataclass
class _UnregisteredPublishAdapter:
    """Honest-failure adapter for an unknown/misconfigured adapter id — it never
    fabricates success (the old behaviour silently fell back to a success-returning
    sandbox adapter, which could mask a CDP misconfiguration as a real publish)."""

    requested_id: str

    @property
    def adapter_id(self) -> str:
        return self.requested_id or "unknown"

    def _reason(self) -> str:
        return f"未注册的发布适配器: {self.requested_id}"

    def probe_accounts(
        self,
        *,
        account_group: str | None = None,
        case_name: str | None = None,
    ) -> tuple[list[PlatformAccount], bool, str | None]:
        return [], False, self._reason()

    def publish(self, payload: PublishPayload) -> PublishOutcome:
        results = [
            {"platform": platform, "success": False, "error": self._reason()}
            for platform in payload.platforms
        ] or [{"success": False, "error": self._reason()}]
        return PublishOutcome(
            success=False, adapter_id=self.adapter_id, results=results, error_message=self._reason()
        )


def select_adapter(explicit: str | None = None) -> PublishPlatformAdapter:
    """Select a publish adapter by id, defaulting to the 小V猫 CDP adapter.

    An unknown/misconfigured id NEVER silently falls back to a success-returning
    adapter: the sandbox no-op is only used when explicitly opted in
    (``CUTAGENT_ALLOW_SANDBOX_FALLBACK=1`` — tests / dry runs); otherwise an unknown
    id resolves to an honest-failure adapter.
    """
    adapter_id = resolve_adapter_id(explicit)
    factory = _PUBLISH_ADAPTERS.get(adapter_id)
    if factory is not None:
        return factory()
    if os.getenv("CUTAGENT_ALLOW_SANDBOX_FALLBACK") == "1":
        return SandboxPublishAdapter()
    return _UnregisteredPublishAdapter(adapter_id)
