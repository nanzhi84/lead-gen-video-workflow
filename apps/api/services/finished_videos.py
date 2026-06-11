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

def performance_attribution(request: Request, video_version_id: str) -> c.PerformanceAttributionResponse:

    if production_repository(request) is not None:
        attribution = production_repository(request).performance_attribution(video_version_id)
        if attribution is None:
            raise NodeExecutionError(c.ErrorCode.artifact_missing, "Video version is missing.")
        return attribution
    video = repository(request).video_versions[video_version_id]
    return c.PerformanceAttributionResponse(
        video_version_id=video_version_id,
        feature_vector=c.CreativeFeatureVector(broll_count=1),
        observations=[item for item in repository(request).performance_observations.values() if item.case_id == video.case_id],
        contributing_memories=[item for item in repository(request).memories.values() if item.case_id == video.case_id],
    )


def case_finished_videos(request: Request, case_id: str, limit: int = 50) -> c.PageResponse[c.FinishedVideo]:

    if production_repository(request) is not None:
        values = production_repository(request).list_finished_videos(case_id=case_id, limit=limit)
        return c.PageResponse(items=values, total_hint=len(values), request_id=request_id())
    return page([item for item in repository(request).finished_videos.values() if item.case_id == case_id], limit)


def finished_video_detail(request: Request, id: str) -> c.FinishedVideoDetail:

    if production_repository(request) is not None:
        detail = production_repository(request).finished_video_detail(id)
        if detail is None:
            raise NodeExecutionError(c.ErrorCode.artifact_missing, "Finished video is missing.")
        return detail
    finished = repository(request).finished_videos[id]
    version = next(
        (item for item in repository(request).video_versions.values() if item.finished_video_id == id),
        None,
    )
    records = [item for item in repository(request).publish_records.values() if item.video_version_id == (version.id if version else None)]
    return c.FinishedVideoDetail(finished_video=finished, video_version=version, publish_records=records)


def finished_video_preview(request: Request, id: str) -> c.SignedUrlResponse:

    if production_repository(request) is not None:
        uri = production_repository(request).artifact_uri_for_finished_video(id)
        if uri is None:
            raise NodeExecutionError(c.ErrorCode.artifact_missing, "Finished video is missing.")
        if uri:
            return object_store(request).signed_url(uri).model_copy(update={"request_id": request_id()})
        return signed(request, f"finished-videos/{id}/preview.mp4")
    finished = repository(request).finished_videos[id]
    artifact = repository(request).artifacts.get(finished.video_artifact.artifact_id)
    if artifact and artifact.uri:
        return object_store(request).signed_url(artifact.uri).model_copy(update={"request_id": request_id()})
    return signed(request, f"finished-videos/{id}/preview.mp4")


def finished_video_download(request: Request, id: str) -> c.SignedUrlResponse:

    return finished_video_preview(request, id)


def delete_finished_video(id: str, request: Request) -> c.OkResponse:
    if production_repository(request) is not None:
        production_repository(request).delete_finished_video(id)
        return c.OkResponse(request_id=request_id())
    repository(request).finished_videos.pop(id, None)
    return c.OkResponse(request_id=request_id())


def editor_handoff(
    id: str, payload: c.CreateEditorHandoffRequest, request: Request
) -> c.EditorHandoffPackageArtifact:
    if production_repository(request) is not None:
        return production_repository(request).create_editor_handoff(id, payload)
    artifact = repository(request).create_artifact(
        kind=c.ArtifactKind.editor_handoff,
        payload_schema="EditorHandoffPackageArtifact.v1",
        payload={"finished_video_id": id, "format": payload.format},
        uri=f"sandbox://handoff/{id}.zip",
    )
    return c.EditorHandoffPackageArtifact(
        package_artifact=repository(request).artifact_ref(artifact.id),
        manifest={"finished_video_id": id, "format": payload.format},
    )


def jianying_draft(
    id: str, payload: c.CreateJianyingDraftRequest, request: Request
) -> c.JianyingDraftPackageArtifact:
    if production_repository(request) is not None:
        return production_repository(request).create_jianying_draft(id, payload)
    artifact = repository(request).create_artifact(
        kind=c.ArtifactKind.jianying_draft,
        payload_schema="JianyingDraftPackageArtifact.v1",
        payload={"finished_video_id": id, "template_id": payload.template_id},
        uri=f"sandbox://jianying/{id}.zip",
    )
    return c.JianyingDraftPackageArtifact(
        package_artifact=repository(request).artifact_ref(artifact.id),
        draft_manifest={"finished_video_id": id, "template_id": payload.template_id or "default"},
    )
