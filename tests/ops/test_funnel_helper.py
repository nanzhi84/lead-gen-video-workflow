"""Unit coverage for the centralized yield-funnel write helper (G3).

These tests exercise ``packages.ops.funnel.record_funnel_event`` directly against
the in-memory ``Repository`` so they run without any DB / FastAPI wiring.
"""

from __future__ import annotations

from packages.core.contracts import RunStatus
from packages.core.storage.repository import Repository
from packages.ops.funnel import (
    FUNNEL_TAXONOMY,
    record_funnel_event,
    workflow_stage,
)


def test_workflow_stage_maps_runstatus_and_string():
    assert workflow_stage(RunStatus.running) == "workflow_running"
    assert workflow_stage(RunStatus.succeeded) == "workflow_succeeded"
    assert workflow_stage("admitted") == "workflow_admitted"


def test_workflow_taxonomy_covers_every_runstatus():
    for status in RunStatus:
        assert workflow_stage(status) in FUNNEL_TAXONOMY


def test_record_funnel_event_writes_and_links_ids():
    repo = Repository()
    record_funnel_event(
        repo,
        event_type="workflow_running",
        job_id="job_1",
        run_id="run_1",
        dedupe_aggregate_id="run_1",
    )
    events = [event for event in repo.yield_events.values() if event.event_type == "workflow_running"]
    assert len(events) == 1
    event = events[0]
    assert event.run_id == "run_1"
    assert event.job_id == "job_1"
    assert event.dedupe_key == "run_1:workflow_running"


def test_record_funnel_event_derives_dedupe_key_from_most_specific_id():
    repo = Repository()
    record_funnel_event(
        repo,
        event_type="publish_attempt_succeeded",
        run_id="run_1",
        publish_attempt_id="att_9",
    )
    event = next(e for e in repo.yield_events.values() if e.event_type == "publish_attempt_succeeded")
    assert event.dedupe_key == "att_9:publish_attempt_succeeded"
    assert event.publish_attempt_id == "att_9"


def test_record_funnel_event_dedupes_on_repeat():
    repo = Repository()
    for _ in range(3):
        record_funnel_event(
            repo,
            event_type="workflow_succeeded",
            run_id="run_dup",
            dedupe_aggregate_id="run_dup",
        )
    matching = [e for e in repo.yield_events.values() if e.dedupe_key == "run_dup:workflow_succeeded"]
    assert len(matching) == 1


def test_record_funnel_event_is_non_fatal(monkeypatch):
    repo = Repository()

    def boom(**kwargs):
        raise RuntimeError("simulated funnel write failure")

    monkeypatch.setattr(repo, "record_yield_funnel_event", boom)
    # Must not raise — emission failures are best-effort and may never break flow.
    record_funnel_event(repo, event_type="workflow_failed", run_id="run_x", dedupe_aggregate_id="run_x")
