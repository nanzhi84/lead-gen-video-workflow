from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request, Response, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse

from apps.api.dependencies import require_role
from apps.api.services import voices as service
from packages.core import contracts as c

router = APIRouter()

@router.get("/api/voices", response_model=c.PageResponse[c.VoiceProfile])
def list_voices(
    request: Request,
    limit: int = 50,
    source: str | None = None,
    enabled: bool | None = None,
) -> c.PageResponse[c.VoiceProfile]:
    return service.list_voices(request, limit, source, enabled)


@router.post("/api/voices/clone", response_model=c.VoiceProfile, status_code=202)
def clone_voice(payload: c.CloneVoiceRequest, request: Request) -> c.VoiceProfile:
    require_role(request, c.UserRole.operator)
    return service.clone_voice(payload, request)


@router.post("/api/voices/design", response_model=c.VoiceProfile, status_code=202)
def design_voice(payload: c.DesignVoiceRequest, request: Request) -> c.VoiceProfile:
    require_role(request, c.UserRole.operator)
    return service.design_voice(payload, request)


@router.post("/api/voices/{voice_id}/preview", response_model=c.VoicePreviewResponse)
def voice_preview(voice_id: str, payload: c.VoicePreviewRequest, request: Request) -> c.VoicePreviewResponse:
    require_role(request, c.UserRole.operator)
    return service.voice_preview(voice_id, payload, request)


@router.patch("/api/voices/{voice_id}", response_model=c.VoiceProfile)
def patch_voice(voice_id: str, payload: c.PatchVoiceRequest, request: Request) -> c.VoiceProfile:
    require_role(request, c.UserRole.operator)
    return service.patch_voice(voice_id, payload, request)


@router.delete("/api/voices/{voice_id}", response_model=c.OkResponse)
def delete_voice(voice_id: str, request: Request) -> c.OkResponse:
    require_role(request, c.UserRole.admin)
    return service.delete_voice(voice_id, request)
