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

def import_batch(payload: c.CreateImportBatchRequest, request: Request) -> c.ImportBatchReport:
    if production_repository(request) is not None:
        report = production_repository(request).create_import_batch(payload, request_id())
        if report is not None:
            return report
    rows = payload.rows or []
    results = []
    created = 0
    failed = 0
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            failed += 1
            results.append(
                c.ImportRowResult(
                    row_index=index,
                    status="failed",
                    error=c.NodeError(
                        code=c.ErrorCode.validation_invalid_options,
                        message="Import row must be an object.",
                    ),
                )
            )
            continue
        internal_id = new_id(payload.import_type)
        if not payload.dry_run:
            if payload.import_type == "case":
                case = c.CaseDetail(
                    id=internal_id,
                    name=str(row.get("name", "Imported case")),
                    owner_user_id="usr_admin",
                    description=str(row.get("description", "")),
                )
                repository(request).cases[case.id] = case
            elif payload.import_type == "script":
                script = c.ScriptVersion(
                    id=internal_id,
                    case_id=str(row.get("case_id", "case_demo")),
                    title=str(row.get("title", "Imported script")),
                    script=str(row.get("script", "")),
                )
                repository(request).scripts[script.id] = script
            elif payload.import_type == "media":
                asset = c.MediaAssetRecord(
                    id=internal_id,
                    case_id=str(row.get("case_id", "case_demo")),
                    title=str(row.get("title", "Imported media")),
                    kind=str(row.get("kind", "other")),
                    annotation_status="pending",
                )
                repository(request).media_assets[asset.id] = asset
            elif payload.import_type == "finished_video":
                artifact = repository(request).create_artifact(
                    kind=c.ArtifactKind.video_finished,
                    payload_schema="ImportedFinishedVideoArtifact.v1",
                    payload={"external_id": row.get("external_id")},
                    uri=str(row.get("uri", f"sandbox://import/{internal_id}.mp4")),
                )
                finished = c.FinishedVideo(
                    id=internal_id,
                    case_id=str(row.get("case_id", "case_demo")),
                    title=str(row.get("title", "Imported finished video")),
                    video_artifact=repository(request).artifact_ref(artifact.id),
                    duration_sec=float(row.get("duration_sec", 0)),
                    qc_status=str(row.get("qc_status", "pending")),
                )
                repository(request).finished_videos[finished.id] = finished
            elif payload.import_type == "video_version":
                version = c.VideoVersion(
                    id=internal_id,
                    case_id=str(row.get("case_id", "case_demo")),
                    script_version_id=str(row.get("script_version_id")) if row.get("script_version_id") else None,
                    finished_video_id=str(row.get("finished_video_id")) if row.get("finished_video_id") else None,
                    timeline_plan_artifact_id=str(row.get("timeline_plan_artifact_id", "imported")),
                    style_plan_artifact_id=str(row.get("style_plan_artifact_id", "imported")),
                )
                repository(request).video_versions[version.id] = version
            elif payload.import_type == "publish_record":
                record = c.PublishRecord(
                    id=internal_id,
                    case_id=str(row.get("case_id", "case_demo")),
                    video_version_id=str(row.get("video_version_id")) if row.get("video_version_id") else None,
                    platform=str(row.get("platform", "manual")),
                    status=str(row.get("status", "published")),
                    published_at=c.utcnow(),
                )
                repository(request).publish_records[record.id] = record
            elif payload.import_type == "performance":
                obs = c.PerformanceObservation(
                    id=internal_id,
                    case_id=str(row.get("case_id", "case_demo")),
                    publish_record_id=str(row.get("publish_record_id", "manual")),
                    metric_name=str(row.get("metric_name", "views")),
                    metric_value=float(row.get("metric_value", 0)),
                )
                repository(request).performance_observations[obs.id] = obs
            elif payload.import_type == "prompt_seed":
                template = c.PromptTemplate(
                    id=internal_id,
                    name=str(row.get("name", "Imported prompt")),
                    purpose=str(row.get("purpose", "imported")),
                    variables_schema_ref=c.PromptSchemaRef(schema_id=str(row.get("variables_schema_id", "imported.variables"))),
                    output_schema_ref=c.PromptSchemaRef(schema_id=str(row.get("output_schema_id", "imported.output"))),
                    status="active",
                )
                version = c.PromptVersion(
                    id=new_id("pver"),
                    prompt_template_id=template.id,
                    content=str(row.get("content", "")),
                    status="published",
                    approved_at=c.utcnow(),
                    published_at=c.utcnow(),
                )
                repository(request).prompt_templates[template.id] = template
                repository(request).prompt_versions[version.id] = version
            elif payload.import_type == "provider_price":
                catalog = c.ProviderPriceCatalog(
                    id=internal_id,
                    provider_id=str(row.get("provider_id", "sandbox")),
                    status="published",
                    currency=str(row.get("currency", "CNY")),
                )
                repository(request).price_catalogs[catalog.id] = catalog
        created += 1
        results.append(
            c.ImportRowResult(
                row_index=index,
                status="created",
                external_id=str(row.get("external_id")) if row.get("external_id") else None,
                internal_id=internal_id,
            )
        )
    report = c.ImportBatchReport(
        batch_id=new_id("imp"),
        import_type=payload.import_type,
        status=c.ImportBatchStatus.completed if failed == 0 else c.ImportBatchStatus.partially_failed,
        created_count=created,
        skipped_count=0,
        failed_count=failed,
        results=results,
        request_id=request_id(),
    )
    repository(request).import_reports[report.batch_id] = report
    return report


def import_batch_detail(request: Request, batch_id: str) -> c.ImportBatchReport:

    if production_repository(request) is not None:
        report = production_repository(request).get_import_batch(batch_id)
        if report is not None:
            return report
    return repository(request).import_reports[batch_id]
