from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request, Response, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse

from apps.api.dependencies import require_role
from apps.api.services import media as service
from packages.core import contracts as c

router = APIRouter()

@router.get("/api/media/assets", response_model=c.PageResponse[c.MediaAssetCard])
def list_media_assets(
    request: Request,
    limit: int = 50,
    case_id: str | None = None,
    kind: str | None = None,
    annotation_status: str | None = None,
) -> c.PageResponse[c.MediaAssetCard]:
    return service.list_media_assets(request, limit, case_id, kind, annotation_status)


@router.post("/api/media/assets", response_model=c.MediaAssetRecord, status_code=201)
def create_media_asset(payload: c.CreateMediaAssetFromUploadRequest, request: Request) -> c.MediaAssetRecord:
    require_role(request, c.UserRole.operator)
    return service.create_media_asset(payload, request)


@router.get("/api/media/assets/{asset_id}", response_model=c.MediaAssetDetail)
def media_asset_detail(request: Request, asset_id: str) -> c.MediaAssetDetail:

    return service.media_asset_detail(request, asset_id)


@router.get("/api/media/assets/{asset_id}/preview-url", response_model=c.SignedUrlResponse)
def media_asset_preview(request: Request, asset_id: str) -> c.SignedUrlResponse:

    return service.media_asset_preview(request, asset_id)


@router.get("/api/annotations/{asset_id}", response_model=c.AnnotationEditorVm)
def get_annotation(request: Request, asset_id: str) -> c.AnnotationEditorVm:

    return service.get_annotation(request, asset_id)


@router.patch("/api/annotations/{asset_id}", response_model=c.AnnotationEditorVm)
def patch_annotation(asset_id: str, payload: c.PatchAnnotationRequest, request: Request) -> c.AnnotationEditorVm:
    require_role(request, c.UserRole.operator)
    return service.patch_annotation(asset_id, payload, request)


@router.post("/api/annotations/{asset_id}/rerun", response_model=c.AnnotationRunResponse, status_code=202)
def rerun_annotation(
    asset_id: str, payload: c.RerunAnnotationRequest, request: Request
) -> c.AnnotationRunResponse:
    require_role(request, c.UserRole.operator)
    return service.rerun_annotation(asset_id, payload, request)
