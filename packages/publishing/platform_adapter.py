"""PublishPlatformAdapter port + adapters.

The publish subsystem talks to platforms through the ``PublishPlatformAdapter``
port. ``SandboxPublishAdapter`` (``adapter_id="sandbox.publish"``) is the
default implementation: an in-process state-machine adapter that walks the
publish_item/publish_batch lifecycle and records ``PublishAttempt`` rows without
touching any external platform.

``select_adapter`` chooses the adapter from an explicit override, then the
``CUTAGENT_PUBLISH_ADAPTER`` feature flag, defaulting to sandbox so production
stays a safe no-op until a real platform adapter is registered.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

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


# Registered publish adapters by id. The real platform adapter (CDP-driven 小V猫)
# registers here in PR2; until then production publishing stays a sandbox no-op.
_PUBLISH_ADAPTERS: dict[str, Callable[[], PublishPlatformAdapter]] = {
    SANDBOX_ADAPTER_ID: SandboxPublishAdapter,
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
