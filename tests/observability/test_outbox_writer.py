from __future__ import annotations

from datetime import datetime, timedelta, timezone

from packages.core.contracts import YieldFunnelEvent
from packages.core.observability.outbox import OutboxWriter
from packages.core.storage.repository import Repository


def test_in_memory_outbox_writer_is_idempotent_by_dedupe_key() -> None:
    repository = Repository()
    writer = OutboxWriter.in_memory(repository)
    payload = {
        "event_id": "evt_run_1",
        "run_id": "run_1",
        "job_id": "job_1",
        "event_type": "run_update",
        "status": "running",
        "message": "Run started.",
        "created_at": "2026-06-11T00:00:00+00:00",
    }

    first = writer.write(
        topic="workflow.run.updated",
        aggregate_type="run",
        aggregate_id="run_1",
        payload_schema="RunEvent.v1",
        payload=payload,
        dedupe_key="run_1:running",
    )
    second = writer.write(
        topic="workflow.run.updated",
        aggregate_type="run",
        aggregate_id="run_1",
        payload_schema="RunEvent.v1",
        payload={**payload, "message": "Duplicate should not replace."},
        dedupe_key="run_1:running",
    )

    assert first.id == second.id
    assert len(repository.outbox) == 1
    assert next(iter(repository.outbox.values())).payload["message"] == "Run started."


def test_in_memory_outbox_replay_is_stably_ordered_by_created_at_and_id() -> None:
    repository = Repository()
    writer = OutboxWriter.in_memory(repository)
    now = datetime(2026, 6, 11, tzinfo=timezone.utc)

    later = writer.write(
        topic="workflow.node.updated",
        aggregate_type="run",
        aggregate_id="run_1",
        payload_schema="RunEvent.v1",
        payload={"event_id": "evt_later", "run_id": "run_1", "job_id": "job_1", "event_type": "node_update"},
        dedupe_key="node_2:running",
        created_at=now + timedelta(seconds=1),
        event_id="evt_b",
    )
    earlier = writer.write(
        topic="workflow.run.updated",
        aggregate_type="run",
        aggregate_id="run_1",
        payload_schema="RunEvent.v1",
        payload={"event_id": "evt_earlier", "run_id": "run_1", "job_id": "job_1", "event_type": "run_update"},
        dedupe_key="run_1:running",
        created_at=now,
        event_id="evt_c",
    )
    tie = writer.write(
        topic="workflow.node.updated",
        aggregate_type="run",
        aggregate_id="run_1",
        payload_schema="RunEvent.v1",
        payload={"event_id": "evt_tie", "run_id": "run_1", "job_id": "job_1", "event_type": "node_update"},
        dedupe_key="node_1:running",
        created_at=now,
        event_id="evt_a",
    )

    replayed = writer.replay(aggregate_type="run", aggregate_id="run_1")

    assert [event.id for event in replayed] == [tie.id, earlier.id, later.id]


def test_yield_funnel_contract_contains_spec_minimum_fields() -> None:
    event = YieldFunnelEvent(
        id="yield_1",
        job_id="job_1",
        run_id="run_1",
        finished_video_id="fv_1",
        publish_package_id="pkg_1",
        publish_attempt_id="attempt_1",
        event_type="workflow_succeeded",
        event_time=datetime(2026, 6, 11, tzinfo=timezone.utc),
        dedupe_key="job_1:workflow_succeeded",
    )

    dumped = event.model_dump()

    assert {
        "job_id",
        "run_id",
        "finished_video_id",
        "publish_package_id",
        "publish_attempt_id",
        "event_type",
        "event_time",
        "dedupe_key",
    } <= set(dumped)
