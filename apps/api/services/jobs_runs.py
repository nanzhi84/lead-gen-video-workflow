from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import Request, Response, UploadFile
from fastapi.responses import JSONResponse

from apps.api.common import (
    auth,
    case_learning_repository,
    case_repository,
    ensure_artifact_ref,
    get_case,
    media_repository,
    object_store,
    ops_repository,
    page,
    production_repository,
    prompt_repository,
    provider_repository,
    publishing_repository,
    repository,
    request_id,
    secret_repository,
    secret_store,
    signed,
    upload_repository,
    workflow_runtime,
)
from apps.api.dependencies import SESSION_COOKIE, current_user, not_found_response
from packages.core import contracts as c
from packages.core.auth import SqlAlchemyAuthService
from packages.core.contracts.state_machines import assert_transition
from packages.core.observability import metric_snapshot
from packages.core.registration_codes import hash_registration_code
from packages.core.storage.object_store import parse_local_uri
from packages.core.storage.repository import new_id
from packages.core.workflow import NodeExecutionError

def create_digital_human_job(
    payload: c.CreateDigitalHumanVideoJobRequest, request: Request
) -> c.CreateJobResponse:
    case = get_case(request, payload.case_id)
    if payload.case_id not in repository(request).cases:
        repository(request).cases[payload.case_id] = case
    job = c.Job(
        id=new_id("job"),
        type=c.JobType.digital_human_video,
        case_id=payload.case_id,
        created_by="usr_admin",
        request_schema=payload.schema_version,
        request=payload,
    )
    repository(request).jobs[job.id] = job
    run = workflow_runtime(request).start_digital_human_run(job_id=job.id, mode="new")
    if production_repository(request) is not None:
        production_repository(request).sync_workflow_snapshot(
            job=repository(request).jobs[job.id],
            run=run,
            repository=repository(request),
        )
    return c.CreateJobResponse(job=repository(request).jobs[job.id], initial_run=run, request_id=request_id())


def job_detail(request: Request, job_id: str) -> c.JobDetailResponse:

    if production_repository(request) is not None:
        detail = production_repository(request).job_detail(job_id, request_id())
        if detail is not None:
            return detail
    job = repository(request).jobs[job_id]
    runs = [run for run in repository(request).runs.values() if run.job_id == job_id]
    return c.JobDetailResponse(
        job=job,
        runs=runs,
        latest_report_artifact_id=runs[-1].public_report_artifact_id if runs else None,
        request_id=request_id(),
    )


def create_run(job_id: str, payload: c.CreateRunRequest, request: Request) -> c.WorkflowRunResponse:
    previous = repository(request).jobs[job_id].active_run_id
    run = workflow_runtime(request).start_digital_human_run(
        job_id=job_id,
        mode=payload.mode,
        from_run_id=previous if payload.mode in {"retry", "resume"} else None,
        reason=payload.reason,
    )
    if production_repository(request) is not None:
        production_repository(request).sync_workflow_snapshot(
            job=repository(request).jobs[job_id],
            run=run,
            repository=repository(request),
        )
    return c.WorkflowRunResponse(run=run, request_id=request_id())


def run_detail(request: Request, run_id: str) -> c.RunDetailResponse:

    if production_repository(request) is not None:
        detail = production_repository(request).run_detail(run_id, request_id())
        if detail is not None:
            return detail
    run = repository(request).runs[run_id]
    node_runs = repository(request).node_runs.get(run_id, [])
    artifacts = [
        repository(request).artifact_ref(artifact.id) for artifact in repository(request).artifacts.values() if artifact.run_id == run_id
    ]
    return c.RunDetailResponse(run=run, node_runs=node_runs, artifacts=artifacts, request_id=request_id())


def cancel_run(run_id: str, payload: c.CancelRunRequest, request: Request) -> c.RunActionResponse:
    run = workflow_runtime(request).cancel_run(run_id, force=payload.force, reason=payload.reason)
    if production_repository(request) is not None:
        production_repository(request).sync_workflow_snapshot(
            job=repository(request).jobs[run.job_id],
            run=run,
            repository=repository(request),
        )
    return c.RunActionResponse(run=run, accepted=True, request_id=request_id())


def retry_run(run_id: str, payload: c.RetryRunRequest, request: Request) -> c.RetryRunResponse:
    run = repository(request).runs[run_id]
    new_run = workflow_runtime(request).start_digital_human_run(
        job_id=run.job_id,
        mode="retry",
        from_run_id=run_id,
        reason=payload.reason,
    )
    if production_repository(request) is not None:
        production_repository(request).sync_workflow_snapshot(
            job=repository(request).jobs[new_run.job_id],
            run=new_run,
            repository=repository(request),
        )
    return c.RetryRunResponse(run=new_run, request_id=request_id())


def resume_run(run_id: str, payload: c.ResumeRunRequest, request: Request) -> c.ResumeRunResponse:
    run = repository(request).runs[run_id]
    new_run = workflow_runtime(request).start_digital_human_run(
        job_id=run.job_id,
        mode="resume",
        from_run_id=run_id if payload.reuse_valid_artifacts else None,
        reason=payload.reason,
    )
    if production_repository(request) is not None:
        production_repository(request).sync_workflow_snapshot(
            job=repository(request).jobs[new_run.job_id],
            run=new_run,
            repository=repository(request),
        )
    return c.ResumeRunResponse(run=new_run, request_id=request_id())


def run_report(request: Request, run_id: str) -> c.RunReportResponse:

    if production_repository(request) is not None:
        report = production_repository(request).run_report(run_id, request_id())
        if report is not None:
            return report
    run = repository(request).runs[run_id]
    if not run.public_report_artifact_id:
        raise NodeExecutionError(c.ErrorCode.artifact_missing, "Run report is not available.")
    public_payload = repository(request).artifacts[run.public_report_artifact_id].payload
    debug_payload = (
        repository(request).artifacts[run.debug_report_artifact_id].payload if run.debug_report_artifact_id else None
    )
    return c.RunReportResponse(
        public_report=c.RunPublicReportArtifact.model_validate(public_payload),
        debug_report=c.RunDebugReportArtifact.model_validate(debug_payload) if debug_payload else None,
        request_id=request_id(),
    )


def run_artifacts(request: Request, run_id: str) -> c.RunArtifactsResponse:

    if production_repository(request) is not None:
        response = production_repository(request).run_artifacts(run_id, request_id())
        if response is not None:
            return response
    refs = [repository(request).artifact_ref(item.id) for item in repository(request).artifacts.values() if item.run_id == run_id]
    return c.RunArtifactsResponse(run_id=run_id, artifacts=refs, request_id=request_id())


def run_events(request: Request, run_id: str) -> c.EventStreamTokenResponse:

    if production_repository(request) is not None and not production_repository(request).run_exists(run_id):
        raise NodeExecutionError(c.ErrorCode.validation_invalid_options, f"Run {run_id} does not exist.")
    return c.EventStreamTokenResponse(
        stream_url=f"/api/ws/runs/{run_id}",
        token=new_id("stream"),
        expires_at=c.utcnow() + timedelta(minutes=10),
        request_id=request_id(),
    )
