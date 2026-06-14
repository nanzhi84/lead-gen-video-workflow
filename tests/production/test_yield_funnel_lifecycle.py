"""G3: the digital-human pipeline emits a funnel event at every run lifecycle
stage it controls (running / succeeded / failed / cancelling / cancelled).

These drive the adapter's lifecycle methods directly against the in-memory
``Repository`` so they run without ffmpeg / the full node sequence.
"""

from __future__ import annotations

from packages.core.contracts import (
    DigitalHumanVideoRequest,
    ErrorCode,
    Job,
    JobStatus,
    JobType,
    RunStatus,
    WorkflowRun,
)
from packages.core.workflow import NodeExecutionError
from packages.core.storage.repository import Repository
from packages.production.pipeline.digital_human import LocalRuntimeAdapter, RunState


def _adapter_with_run(status: RunStatus) -> tuple[LocalRuntimeAdapter, WorkflowRun, Job]:
    repository = Repository()
    adapter = object.__new__(LocalRuntimeAdapter)
    adapter.repository = repository
    job = Job(
        id="job_funnel",
        type=JobType.digital_human_video,
        status=JobStatus.running,
        case_id="case_demo",
        request_schema="DigitalHumanVideoRequest.v1",
        request=DigitalHumanVideoRequest(
            case_id="case_demo",
            script="hello",
            voice={"voice_id": "voice_sandbox"},
        ),
    )
    run = WorkflowRun(
        id="run_funnel",
        job_id=job.id,
        case_id="case_demo",
        workflow_template_id="digital_human_v2",
        workflow_version="v1",
        status=status,
    )
    repository.jobs[job.id] = job
    repository.runs[run.id] = run
    repository.node_runs[run.id] = []
    return adapter, run, job


def _event_types(repository: Repository) -> set[str]:
    return {event.event_type for event in repository.yield_events.values()}


def test_complete_run_emits_workflow_succeeded():
    adapter, run, job = _adapter_with_run(RunStatus.running)
    adapter._complete_run(run.id)
    assert "workflow_succeeded" in _event_types(adapter.repository)
    event = next(e for e in adapter.repository.yield_events.values() if e.event_type == "workflow_succeeded")
    assert event.dedupe_key == "run_funnel:workflow_succeeded"
    assert event.run_id == run.id
    assert event.job_id == job.id


def test_mark_cancelled_from_running_emits_cancelling_and_cancelled():
    adapter, run, _ = _adapter_with_run(RunStatus.running)
    adapter._mark_cancelled(run.id)
    types = _event_types(adapter.repository)
    assert "workflow_cancelling" in types
    assert "workflow_cancelled" in types


def test_node_failure_emits_workflow_failed():
    adapter, run, _ = _adapter_with_run(RunStatus.running)
    state = RunState(
        request=DigitalHumanVideoRequest(
            case_id="case_demo",
            script="hello",
            voice={"voice_id": "voice_sandbox"},
        )
    )

    def boom(node_id, run_arg, node_run, state_arg):  # noqa: ANN001 - test stub
        raise NodeExecutionError(ErrorCode.validation_invalid_options, "boom")

    adapter._run_node = boom  # type: ignore[method-assign]
    proceeded = adapter._execute_node("ValidateRequest", run, state)
    assert proceeded is False
    assert "workflow_failed" in _event_types(adapter.repository)
    event = next(e for e in adapter.repository.yield_events.values() if e.event_type == "workflow_failed")
    assert event.dedupe_key == "run_funnel:workflow_failed"
