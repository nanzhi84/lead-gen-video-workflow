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

def prepare_upload(payload: c.PrepareUploadRequest, request: Request) -> c.UploadSession:
    object_ref = object_store(request).prepare_upload(payload.filename, payload.kind.value)
    upload = c.UploadSession(
        id=new_id("upl"),
        kind=payload.kind,
        case_id=payload.case_id,
        filename=payload.filename,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
        sha256=payload.sha256,
        upload_url=object_store(request).signed_url(object_ref.uri).url,
        object_uri=object_ref.uri,
    )
    if upload_repository(request) is not None:
        return upload_repository(request).create_upload(upload)
    repository(request).uploads[upload.id] = upload
    return upload


async def upload_file(
    upload_session_id: str, request: Request, file: UploadFile | None = None
) -> c.UploadSession:
    if upload_repository(request) is not None:
        upload = upload_repository(request).get_upload(upload_session_id)
    else:
        upload = repository(request).uploads.get(upload_session_id)
    if upload is None:
        raise NodeExecutionError(c.ErrorCode.upload_invalid_state, "Upload session not found.")
    if file is not None and upload.object_uri:
        content = await file.read()
        stored = object_store(request).put_bytes(parse_local_uri(upload.object_uri), content)
        if stored.size_bytes != upload.size_bytes:
            raise NodeExecutionError(c.ErrorCode.upload_size_mismatch, "Upload size mismatch.")
        if upload.sha256 and upload.sha256 != stored.sha256:
            raise NodeExecutionError(c.ErrorCode.upload_sha256_mismatch, "Upload sha256 mismatch.")
        updates = {"status": c.UploadStatus.uploading, "sha256": upload.sha256 or stored.sha256}
    else:
        updates = {"status": c.UploadStatus.uploading}
    if upload_repository(request) is not None:
        return upload_repository(request).patch_upload(upload_session_id, updates)
    if "status" in updates:
        assert_transition("upload_session", upload.status, updates["status"])
    return repository(request).patch(repository(request).uploads, upload_session_id, updates)


def complete_upload(payload: c.CompleteUploadRequest, request: Request) -> c.CompleteUploadResponse:
    upload = (
        upload_repository(request).get_upload(payload.upload_session_id)
        if upload_repository(request) is not None
        else repository(request).uploads[payload.upload_session_id]
    )
    if upload is None:
        raise NodeExecutionError(c.ErrorCode.upload_invalid_state, "Upload session not found.")
    assert_transition("upload_session", upload.status, c.UploadStatus.completed)
    if payload.size_bytes is not None and payload.size_bytes != upload.size_bytes:
        raise NodeExecutionError(c.ErrorCode.upload_size_mismatch, "Upload size mismatch.")
    if upload.sha256 and payload.sha256 and upload.sha256 != payload.sha256:
        raise NodeExecutionError(c.ErrorCode.upload_sha256_mismatch, "Upload sha256 mismatch.")
    if upload_repository(request) is not None:
        upload = upload_repository(request).patch_upload(upload.id, {"status": c.UploadStatus.completed})
        artifact = upload_repository(request).create_artifact_from_upload(upload)
        artifact_ref = upload_repository(request).artifact_ref(artifact.id)
    else:
        upload = repository(request).patch(repository(request).uploads, upload.id, {"status": c.UploadStatus.completed})
        artifact = repository(request).create_artifact(
            kind=c.ArtifactKind.uploaded_file,
            payload_schema="UploadedFileArtifact.v1",
            payload=upload.model_dump(mode="json"),
            uri=upload.object_uri,
            sha256=upload.sha256,
        )
        artifact_ref = repository(request).artifact_ref(artifact.id)
    media_asset = None
    publish_package = None
    if upload.kind in {
        c.UploadKind.portrait,
        c.UploadKind.broll,
        c.UploadKind.bgm,
        c.UploadKind.font,
        c.UploadKind.cover_template,
    }:
        media_payload = c.CreateMediaAssetFromUploadRequest(
            upload_session_id=upload.id,
            case_id=upload.case_id,
            title=payload.metadata.get("title") or upload.filename,
            kind=upload.kind.value,
            tags=[upload.kind.value, "upload"],
        )
        if media_repository(request) is not None:
            media_asset = media_repository(request).create_asset_from_upload(media_payload)
        else:
            media_asset = c.MediaAssetRecord(
                id=new_id("asset"),
                case_id=media_payload.case_id,
                title=media_payload.title,
                kind=media_payload.kind,
                source_artifact_id=artifact.id,
                tags=media_payload.tags,
            )
            repository(request).media_assets[media_asset.id] = media_asset
    elif upload.kind == c.UploadKind.publish_video:
        package_payload = c.CreatePublishPackageRequest(
            upload_artifact_id=artifact.id,
            title=payload.metadata.get("title") or upload.filename,
            description=payload.metadata.get("description", ""),
        )
        if publishing_repository(request) is not None:
            publish_package = publishing_repository(request).create_package(package_payload)
        else:
            publish_package = c.PublishPackage(
                id=new_id("pkg"),
                case_id=upload.case_id,
                upload_artifact_id=artifact.id,
                video_artifact=artifact_ref,
                platform_defaults=c.PublishDefaults(
                    title=package_payload.title,
                    description=package_payload.description,
                ),
            )
            repository(request).publish_packages[publish_package.id] = publish_package
    return c.CompleteUploadResponse(
        upload_session=upload,
        artifact=artifact_ref,
        media_asset=media_asset,
        publish_package=publish_package,
        request_id=request_id(),
    )


def cancel_upload(upload_session_id: str, request: Request) -> c.UploadSession:
    if upload_repository(request) is not None:
        return upload_repository(request).patch_upload(
            upload_session_id,
            {"status": c.UploadStatus.cancelled},
        )
    upload = repository(request).uploads[upload_session_id]
    assert_transition("upload_session", upload.status, c.UploadStatus.cancelled)
    return repository(request).patch(repository(request).uploads, upload_session_id, {"status": c.UploadStatus.cancelled})


def get_upload(upload_session_id: str, request: Request) -> c.UploadSession:
    if upload_repository(request) is not None:
        upload = upload_repository(request).get_upload(upload_session_id)
        if upload is None:
            raise NodeExecutionError(c.ErrorCode.upload_invalid_state, "Upload session not found.")
        return upload
    return repository(request).uploads[upload_session_id]
