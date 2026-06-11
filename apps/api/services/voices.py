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

def list_voices(
    request: Request,
    limit: int = 50,
    source: str | None = None,
    enabled: bool | None = None,
) -> c.PageResponse[c.VoiceProfile]:
    if media_repository(request) is not None:
        values = media_repository(request).list_voices(source=source, enabled=enabled, limit=limit)
        return c.PageResponse(items=values, total_hint=len(values), request_id=request_id())
    values = list(repository(request).voices.values())
    if source:
        values = [voice for voice in values if voice.source == source]
    if enabled is not None:
        values = [voice for voice in values if voice.enabled == enabled]
    return page(values, limit)


def clone_voice(payload: c.CloneVoiceRequest, request: Request) -> c.VoiceProfile:
    if media_repository(request) is not None:
        return media_repository(request).clone_voice(payload)
    voice = c.VoiceProfile(
        id=new_id("voice"),
        display_name=payload.display_name,
        source="cloned",
        provider_profile_id=payload.provider_profile_id or "sandbox.tts.default",
    )
    repository(request).voices[voice.id] = voice
    return voice


def design_voice(payload: c.DesignVoiceRequest, request: Request) -> c.VoiceProfile:
    if media_repository(request) is not None:
        return media_repository(request).design_voice(payload)
    voice = c.VoiceProfile(
        id=new_id("voice"),
        display_name=payload.display_name,
        source="designed",
        provider_profile_id=payload.provider_profile_id or "sandbox.tts.default",
    )
    repository(request).voices[voice.id] = voice
    return voice


def voice_preview(voice_id: str, payload: c.VoicePreviewRequest, request: Request) -> c.VoicePreviewResponse:
    if media_repository(request) is not None:
        response = media_repository(request).preview_voice(voice_id, payload)
        if response is None:
            raise NodeExecutionError(c.ErrorCode.validation_missing_voice, "Voice not found.")
        return response
    if voice_id not in repository(request).voices:
        raise NodeExecutionError(c.ErrorCode.validation_missing_voice, "Voice not found.")
    artifact = repository(request).create_artifact(
        kind=c.ArtifactKind.audio_tts,
        payload_schema="VoicePreviewArtifact.v1",
        payload={"text": payload.text},
        uri=f"sandbox://voice-preview/{voice_id}.wav",
    )
    return c.VoicePreviewResponse(
        voice_id=voice_id,
        audio_artifact=repository(request).artifact_ref(artifact.id),
        duration_sec=max(1, len(payload.text) / 6),
    )


def patch_voice(voice_id: str, payload: c.PatchVoiceRequest, request: Request) -> c.VoiceProfile:
    if media_repository(request) is not None:
        voice = media_repository(request).patch_voice(voice_id, payload)
        if voice is None:
            raise NodeExecutionError(c.ErrorCode.validation_missing_voice, "Voice not found.")
        return voice
    return repository(request).patch(repository(request).voices, voice_id, payload.model_dump(exclude_none=True))


def delete_voice(voice_id: str, request: Request) -> c.OkResponse:
    if media_repository(request) is not None:
        media_repository(request).delete_voice(voice_id)
        return c.OkResponse(request_id=request_id())
    repository(request).voices.pop(voice_id, None)
    return c.OkResponse(request_id=request_id())
