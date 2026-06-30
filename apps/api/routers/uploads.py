from __future__ import annotations


from fastapi import APIRouter, Request

from apps.api.dependencies import require_role
from apps.api.services import uploads as service
from packages.core import contracts as c

router = APIRouter()

@router.post("/api/uploads/prepare", response_model=c.PrepareUploadResponse, status_code=201)
def prepare_upload(payload: c.PrepareUploadRequest, request: Request) -> c.PrepareUploadResponse:
    require_role(request, c.UserRole.operator)
    return service.prepare_upload(payload, request)


@router.post("/api/uploads/complete", response_model=c.CompleteUploadResponse)
def complete_upload(payload: c.CompleteUploadRequest, request: Request) -> c.CompleteUploadResponse:
    require_role(request, c.UserRole.operator)
    return service.complete_upload(payload, request)


@router.post("/api/uploads/{upload_session_id}/cancel", response_model=c.UploadSession)
def cancel_upload(upload_session_id: str, request: Request) -> c.UploadSession:
    require_role(request, c.UserRole.operator)
    return service.cancel_upload(upload_session_id, request)


@router.get("/api/uploads/{upload_session_id}", response_model=c.UploadSession)
def get_upload(upload_session_id: str, request: Request) -> c.UploadSession:
    require_role(request, c.UserRole.operator)
    return service.get_upload(upload_session_id, request)
