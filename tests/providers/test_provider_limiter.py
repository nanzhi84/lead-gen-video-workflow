"""Isolated tests for the in-process provider concurrency limiter.

These tests use only the in-memory Repository + threads (no Postgres / Temporal /
OSS), so they are safe to run concurrently with other agents.
"""

from __future__ import annotations

import threading
import time

import pytest

from packages.ai.gateway import provider_limiter
from packages.ai.gateway.provider_gateway import (
    ProviderCall,
    ProviderGateway,
    ProviderResult,
)
from packages.core.contracts import (
    ProviderOptionsSchemaRef,
    ProviderProfile,
    ProviderStatus,
)
from packages.core.storage.repository import Repository


class _SlowCountingProvider:
    """Fake provider that sleeps while in-flight and records peak concurrency."""

    provider_id = "fake.slow"

    def __init__(self, hold_sec: float = 0.05) -> None:
        self.hold_sec = hold_sec
        self._lock = threading.Lock()
        self.current = 0
        self.peak = 0

    def invoke(self, call: ProviderCall) -> ProviderResult:
        with self._lock:
            self.current += 1
            self.peak = max(self.peak, self.current)
        try:
            time.sleep(self.hold_sec)
        finally:
            with self._lock:
                self.current -= 1
        return ProviderResult(output={"ok": True})


def _profile(profile_id: str, concurrency_key: str) -> ProviderProfile:
    return ProviderProfile(
        id=profile_id,
        provider_id="fake.slow",
        model_id="fake.local",
        capability="tts.speech",
        display_name="Fake Slow Provider",
        environment="local",
        concurrency_key=concurrency_key,
        options_schema_ref=ProviderOptionsSchemaRef(schema_id="provider.tts.options"),
    )


@pytest.fixture(autouse=True)
def _reset_limiter():
    provider_limiter.reset_limiter_for_tests()
    yield
    provider_limiter.reset_limiter_for_tests()


def _build_gateway(profile: ProviderProfile) -> tuple[ProviderGateway, _SlowCountingProvider]:
    repository = Repository()
    repository.provider_profiles[profile.id] = profile
    # Drop price items so the run does not depend on pricing config.
    repository.price_items.clear()
    gw = ProviderGateway(repository, auto_register_real_plugins=False)
    plugin = _SlowCountingProvider()
    gw.register(plugin)
    return gw, plugin


def _run_concurrent(gw: ProviderGateway, profile_id: str, n: int) -> list[ProviderStatus]:
    results: list[ProviderStatus] = []
    results_lock = threading.Lock()
    start = threading.Barrier(n)

    def worker() -> None:
        start.wait()  # release all threads as simultaneously as possible
        invocation, _ = gw.invoke(
            ProviderCall(
                provider_profile_id=profile_id,
                capability_id="tts.speech",
                input={"text": "hello"},
            )
        )
        with results_lock:
            results.append(invocation.status)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results


def test_concurrent_invokes_on_same_key_never_exceed_cap(monkeypatch):
    monkeypatch.setenv("CUTAGENT_PROVIDER_MAX_INFLIGHT", "3")
    provider_limiter.reset_limiter_for_tests()
    profile = _profile("fake.slow.tts", "fake:tts")
    gw, plugin = _build_gateway(profile)

    statuses = _run_concurrent(gw, profile.id, n=20)

    assert len(statuses) == 20
    assert all(status == ProviderStatus.succeeded for status in statuses)
    # The whole point: peak in-flight for the key must respect the cap.
    assert plugin.peak <= 3
    # And the limiter must actually have run things in parallel (not serialized).
    assert plugin.peak >= 2


def test_default_cap_applies_when_env_unset(monkeypatch):
    monkeypatch.delenv("CUTAGENT_PROVIDER_MAX_INFLIGHT", raising=False)
    provider_limiter.reset_limiter_for_tests()
    profile = _profile("fake.slow.default", "fake:default")
    gw, plugin = _build_gateway(profile)

    statuses = _run_concurrent(gw, profile.id, n=16)

    assert all(status == ProviderStatus.succeeded for status in statuses)
    assert plugin.peak <= provider_limiter.DEFAULT_MAX_INFLIGHT


def test_invalid_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("CUTAGENT_PROVIDER_MAX_INFLIGHT", "not-a-number")
    provider_limiter.reset_limiter_for_tests()
    profile = _profile("fake.slow.invalid", "fake:invalid")
    gw, plugin = _build_gateway(profile)

    statuses = _run_concurrent(gw, profile.id, n=10)

    assert all(status == ProviderStatus.succeeded for status in statuses)
    assert plugin.peak <= provider_limiter.DEFAULT_MAX_INFLIGHT


def test_unrelated_invalid_publishing_port_does_not_break_limiter(monkeypatch):
    monkeypatch.setenv("CUTAGENT_XIAOVMAO_CDP_PORT", "not-a-number")
    monkeypatch.delenv("CUTAGENT_PROVIDER_MAX_INFLIGHT", raising=False)

    assert provider_limiter._max_inflight() == provider_limiter.DEFAULT_MAX_INFLIGHT


def test_separate_keys_have_independent_slots(monkeypatch):
    monkeypatch.setenv("CUTAGENT_PROVIDER_MAX_INFLIGHT", "1")
    provider_limiter.reset_limiter_for_tests()
    repository = Repository()
    repository.price_items.clear()
    profile_a = _profile("fake.slow.a", "fake:a")
    profile_b = _profile("fake.slow.b", "fake:b")
    repository.provider_profiles[profile_a.id] = profile_a
    repository.provider_profiles[profile_b.id] = profile_b
    gw = ProviderGateway(repository, auto_register_real_plugins=False)
    plugin = _SlowCountingProvider()
    gw.register(plugin)

    peak_lock = threading.Lock()
    observed: dict[str, int] = {}

    def fire(profile_id: str) -> None:
        invocation, _ = gw.invoke(
            ProviderCall(
                provider_profile_id=profile_id,
                capability_id="tts.speech",
                input={"text": "x"},
            )
        )
        with peak_lock:
            observed[profile_id] = (
                1 if invocation.status == ProviderStatus.succeeded else 0
            )

    threads = [
        threading.Thread(target=fire, args=(profile_a.id,)),
        threading.Thread(target=fire, args=(profile_b.id,)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    # Cap is 1 per key but there are two distinct keys, so both run together.
    assert plugin.peak == 2
    assert observed == {profile_a.id: 1, profile_b.id: 1}
