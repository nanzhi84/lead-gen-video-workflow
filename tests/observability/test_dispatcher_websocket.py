from __future__ import annotations

from datetime import datetime, timezone

import anyio
from fastapi.testclient import TestClient

from apps.api.main import app
from packages.core.observability.events import InProcessFanoutHub, OutboxDispatcher
from packages.core.observability.outbox import OutboxWriter
from packages.core.storage.repository import Repository


def test_outbox_dispatcher_publishes_pending_events_in_stable_order() -> None:
    repository = Repository()
    hub = InProcessFanoutHub()
    dispatcher = OutboxDispatcher(repository=repository, hub=hub)
    writer = OutboxWriter.in_memory(repository)
    created_at = datetime(2026, 6, 11, tzinfo=timezone.utc)

    writer.write(
        topic="workflow.node.updated",
        aggregate_type="run",
        aggregate_id="run_1",
        payload_schema="RunEvent.v1",
        payload={"event_id": "evt_b", "run_id": "run_1", "job_id": "job_1", "event_type": "node_update"},
        dedupe_key="node:b",
        created_at=created_at,
        event_id="evt_b",
    )
    writer.write(
        topic="workflow.run.updated",
        aggregate_type="run",
        aggregate_id="run_1",
        payload_schema="RunEvent.v1",
        payload={"event_id": "evt_a", "run_id": "run_1", "job_id": "job_1", "event_type": "run_update"},
        dedupe_key="run:a",
        created_at=created_at,
        event_id="evt_a",
    )

    subscriber = hub.subscribe("run_1")
    anyio.run(dispatcher.dispatch_once)

    assert [hub.get_nowait(subscriber)["event_id"], hub.get_nowait(subscriber)["event_id"]] == [
        "evt_a",
        "evt_b",
    ]
    assert [event.status for event in repository.outbox.values()] == ["published", "published"]
    assert [event.attempts for event in repository.outbox.values()] == [1, 1]


def test_run_websocket_replays_history_and_receives_dispatched_events() -> None:
    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"email": "admin@local.cutagent", "password": "local-admin"},
        )
        assert login.status_code == 200, login.text
        repository = client.app.state.repository
        writer = OutboxWriter.in_memory(repository)
        writer.write(
            topic="workflow.run.updated",
            aggregate_type="run",
            aggregate_id="run_ws",
            payload_schema="RunEvent.v1",
            payload={
                "event_id": "evt_history",
                "run_id": "run_ws",
                "job_id": "job_ws",
                "event_type": "run_update",
                "message": "history",
                "created_at": "2026-06-11T00:00:00+00:00",
            },
            dedupe_key="run_ws:history",
            event_id="evt_history",
        )
        anyio.run(client.app.state.outbox_dispatcher.dispatch_once)

        token_response = client.get("/api/runs/run_ws/events")
        assert token_response.status_code == 200, token_response.text
        token_body = token_response.json()
        assert token_body["stream_url"] == "/ws/runs/run_ws"
        assert token_body["token"]

        with client.websocket_connect(f"/ws/runs/run_ws?token={token_body['token']}") as websocket:
            assert websocket.receive_json()["event_id"] == "evt_history"
            repository.create_event(
                "workflow.node.updated",
                "run",
                "run_ws",
                {"job_id": "job_ws", "node_id": "NodeA", "status": "running"},
                dedupe_key="node_a:running",
                event_type="node_update",
                node_id="NodeA",
                status="running",
                message="NodeA is running.",
            )
            anyio.run(client.app.state.outbox_dispatcher.dispatch_once)
            live = websocket.receive_json()

        assert live["event_type"] == "node_update"
        assert live["node_id"] == "NodeA"
        assert live["status"] == "running"
