"""The run event-stream connection gauge must never leak (issue #87 / D1).

``event_stream_connections_active`` is incremented once per accepted connection
and must be decremented in a ``finally`` no matter how the handler unwinds. The bug:
``record_event_stream_connected()`` lived *outside* the ``try`` that owns the
matching ``record_event_stream_disconnected()``, so anything raising between the
two (outbox replay, replay-time ``send_json`` raising ``WebSocketDisconnect``, or
``hub.subscribe``) leaked one connection into the gauge permanently. These tests
pin the invariant: after the connection unwinds — success or failure — the gauge
returns to its pre-connect baseline.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from apps.api.app import create_app
from apps.api.services import jobs_runs
from packages.core.observability.telemetry import EVENT_STREAM_CONNECTIONS_ACTIVE


def _gauge() -> float:
    return EVENT_STREAM_CONNECTIONS_ACTIVE._value.get()


def test_gauge_returns_to_baseline_when_outbox_replay_raises(monkeypatch):
    # Outbox replay runs after accept()/connected() but (pre-fix) before the try:
    # a raise here used to leak the gauge because the finally never ran.
    def _boom(*_args, **_kwargs):
        raise RuntimeError("replay blew up before the subscribe")

    monkeypatch.setattr(jobs_runs, "replay_sqlalchemy_outbox", _boom)

    app = create_app()
    with TestClient(app) as client:
        token = app.state.event_tokens.issue("run_leak_replay", timedelta(minutes=5)).token
        baseline = _gauge()
        # The handler accepts (so the client connects) and then raises during
        # replay; the connection tears down. Swallow whatever the transport
        # surfaces — the only thing under test is the gauge after teardown.
        try:
            with client.websocket_connect(f"/ws/runs/run_leak_replay?token={token}"):
                pass
        except Exception:
            pass
        after = _gauge()

    assert after == baseline, f"connection gauge leaked on replay error: {baseline} -> {after}"


def test_gauge_returns_to_baseline_when_subscribe_raises(monkeypatch):
    # hub.subscribe runs after a successful (empty) replay but (pre-fix) before
    # the try: a raise here also leaked the gauge, and the finally must not call
    # unsubscribe with an undefined/None subscriber.
    def _boom(*_args, **_kwargs):
        raise RuntimeError("subscribe blew up")

    app = create_app()
    with TestClient(app) as client:
        # The hub is (re)built during lifespan startup, so patch it only after
        # the TestClient context has entered — otherwise the handler reads the
        # real, unpatched hub.
        monkeypatch.setattr(app.state.event_hub, "subscribe", _boom)
        token = app.state.event_tokens.issue("run_leak_subscribe", timedelta(minutes=5)).token
        baseline = _gauge()
        try:
            with client.websocket_connect(f"/ws/runs/run_leak_subscribe?token={token}"):
                pass
        except Exception:
            pass
        after = _gauge()

    assert after == baseline, f"connection gauge leaked on subscribe error: {baseline} -> {after}"
