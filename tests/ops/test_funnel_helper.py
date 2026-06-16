"""Unit coverage for the centralized §9.5 yield-funnel write helper (G3).

These tests exercise ``packages.core.observability.funnel`` directly against the
in-memory ``Repository`` so they run without any DB / FastAPI wiring. They also
prove the ``packages.ops`` re-export keeps working (dependency-rule fix: the
helper now lives in ``core.observability`` so production may import it without
depending on ``ops``).
"""

from __future__ import annotations

from packages.core.contracts import NodeStatus, RunStatus
from packages.core.observability import (
    FUNNEL_TAXONOMY,
    compute_true_yield_rate,
    node_stage,
    record_funnel_event,
    workflow_stage,
)
from packages.core.storage.repository import Repository


SPEC_9_5_TAXONOMY = frozenset(
    {
        "submitted",
        "admitted",
        "started",
        "node_started",
        "node_succeeded",
        "node_failed",
        "finished_video_created",
        "qc_started",
        "qc_passed",
        "qc_failed",
        "manual_approved",
        "manual_rejected",
        "publish_started",
        "published",
        "publish_failed",
    }
)


def test_taxonomy_is_exactly_the_spec_9_5_set():
    # FUNNEL_TAXONOMY must equal the §9.5 taxonomy verbatim — no more, no less.
    assert FUNNEL_TAXONOMY == SPEC_9_5_TAXONOMY


def test_workflow_stage_maps_runstatus_to_spec_strings():
    assert workflow_stage(RunStatus.created) == "submitted"
    assert workflow_stage(RunStatus.admitted) == "admitted"
    assert workflow_stage(RunStatus.running) == "started"
    # Terminal run statuses are not §9.5 funnel stages -> None (no emission).
    assert workflow_stage(RunStatus.succeeded) is None
    assert workflow_stage(RunStatus.failed) is None
    assert workflow_stage(RunStatus.cancelled) is None
    # String form works too.
    assert workflow_stage("admitted") == "admitted"


def test_workflow_run_lifecycle_stages_are_in_taxonomy():
    for status in (RunStatus.created, RunStatus.admitted, RunStatus.running):
        assert workflow_stage(status) in FUNNEL_TAXONOMY


def test_node_stage_maps_nodestatus_to_spec_strings():
    assert node_stage(NodeStatus.succeeded) == "node_succeeded"
    assert node_stage(NodeStatus.degraded) == "node_succeeded"
    assert node_stage(NodeStatus.failed) == "node_failed"
    # Non-terminal / skipped node statuses emit nothing.
    assert node_stage(NodeStatus.pending) is None
    assert node_stage(NodeStatus.running) is None
    assert node_stage(NodeStatus.skipped) is None
    assert node_stage("succeeded") == "node_succeeded"


def test_record_funnel_event_writes_and_links_ids():
    repo = Repository()
    record_funnel_event(
        repo,
        event_type="started",
        job_id="job_1",
        run_id="run_1",
        dedupe_aggregate_id="run_1",
    )
    events = [event for event in repo.yield_events.values() if event.event_type == "started"]
    assert len(events) == 1
    event = events[0]
    assert event.run_id == "run_1"
    assert event.job_id == "job_1"
    assert event.dedupe_key == "run_1:started"


def test_record_funnel_event_derives_dedupe_key_from_most_specific_id():
    repo = Repository()
    record_funnel_event(
        repo,
        event_type="node_succeeded",
        run_id="run_1",
        node_run_id="nr_9",
    )
    event = next(e for e in repo.yield_events.values() if e.event_type == "node_succeeded")
    assert event.dedupe_key == "nr_9:node_succeeded"


def test_record_funnel_event_dedupes_on_repeat():
    repo = Repository()
    for _ in range(3):
        record_funnel_event(
            repo,
            event_type="published",
            run_id="run_dup",
            publish_attempt_id="att_dup",
        )
    matching = [e for e in repo.yield_events.values() if e.dedupe_key == "att_dup:published"]
    assert len(matching) == 1


def test_record_funnel_event_is_non_fatal(monkeypatch):
    repo = Repository()

    def boom(**kwargs):
        raise RuntimeError("simulated funnel write failure")

    monkeypatch.setattr(repo, "record_yield_funnel_event", boom)
    # Must not raise — emission failures are best-effort and may never break flow.
    record_funnel_event(repo, event_type="node_failed", run_id="run_x", node_run_id="nr_x")


def _event(run_id, event_type):
    class _E:
        pass

    e = _E()
    e.run_id = run_id
    e.event_type = event_type
    return e


def test_true_yield_rate_is_run_scoped_not_event_count():
    # Two runs entered the funnel; run_a published (true yield), run_b only
    # produced node events. The rate is 1/2 = 0.5 regardless of how many event
    # rows each run wrote (denominator is DISTINCT runs, not total events).
    events = [
        _event("run_a", "submitted"),
        _event("run_a", "node_started"),
        _event("run_a", "node_succeeded"),
        _event("run_a", "finished_video_created"),
        _event("run_a", "publish_started"),
        _event("run_a", "published"),
        _event("run_b", "submitted"),
        _event("run_b", "node_started"),
    ]
    assert compute_true_yield_rate(events) == 0.5


def test_true_yield_rate_excludes_qc_failed_run():
    # A run that reached published but was qc_failed does NOT count as true yield
    # ("技术成功但 QC 不通过不能计入 true yield").
    events = [
        _event("run_a", "published"),
        _event("run_a", "qc_failed"),
        _event("run_b", "published"),
    ]
    # run_a disqualified by qc_failed; run_b is true yield -> 1/2.
    assert compute_true_yield_rate(events) == 0.5


def test_true_yield_rate_excludes_manual_rejected_run():
    events = [
        _event("run_a", "published"),
        _event("run_a", "manual_rejected"),
        _event("run_b", "published"),
        _event("run_b", "manual_approved"),
    ]
    assert compute_true_yield_rate(events) == 0.5


def test_true_yield_rate_none_without_run_scoped_events():
    assert compute_true_yield_rate([]) is None
    assert compute_true_yield_rate([_event(None, "published")]) is None
