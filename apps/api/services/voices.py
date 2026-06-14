from __future__ import annotations


from fastapi import Request

from apps.api.common import (
    media_repository,
    page,
    repository,
    request_id,
)
from packages.core import contracts as c
from packages.core.config.settings import sandbox_fallback_allowed
from packages.core.storage.repository import new_id
from packages.core.workflow import NodeExecutionError
from packages.ai.gateway import ProviderCall
from packages.media.voice_provider_bridge import (
    hydrate_voice_reference_upload,
    load_voice,
    persist_provider_preview,
    persist_provider_voice,
)


def _voice_tts_profile_id(provider_profile_id: str | None) -> str:
    """Resolve the TTS provider profile for a new voice, or fail loudly.

    Without an explicit real profile the running app refuses to mint a voice
    bound to the seeded sandbox TTS; only the opt-in sandbox path keeps the old
    fallback (tests / local sandbox)."""
    if provider_profile_id:
        return provider_profile_id
    if sandbox_fallback_allowed():
        return "sandbox.tts.default"
    raise NodeExecutionError(
        c.ErrorCode.provider_unsupported_option,
        "未指定真实 TTS 供应商配置。请先在「设置」中配置并启用真实 TTS 供应商，再克隆 / 设计音色。",
    )

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
    media_repo = media_repository(request)
    if media_repo is not None:
        provider_voice = _provider_voice_build(
            payload.provider_profile_id,
            request,
            operation="clone",
            display_name=payload.display_name,
            source="cloned",
            input_payload={"reference_upload_session_id": payload.reference_upload_session_id},
            before_invoke=lambda repo: hydrate_voice_reference_upload(
                media_repo, repo, payload.reference_upload_session_id
            ),
        )
        if provider_voice is not None:
            return persist_provider_voice(media_repo, provider_voice)
        # No real provider voice was built (no provider_profile_id). Enforce the
        # same loud-fail gate as the in-memory path before the repo silently binds
        # the new voice to sandbox.tts.default.
        resolved = _voice_tts_profile_id(payload.provider_profile_id)
        return media_repo.clone_voice(payload.model_copy(update={"provider_profile_id": resolved}))
    provider_voice = _provider_voice_build(
        payload.provider_profile_id,
        request,
        operation="clone",
        display_name=payload.display_name,
        source="cloned",
        input_payload={"reference_upload_session_id": payload.reference_upload_session_id},
    )
    if provider_voice is not None:
        return provider_voice
    voice = c.VoiceProfile(
        id=new_id("voice"),
        display_name=payload.display_name,
        source="cloned",
        provider_profile_id=_voice_tts_profile_id(payload.provider_profile_id),
    )
    repository(request).voices[voice.id] = voice
    return voice


def design_voice(payload: c.DesignVoiceRequest, request: Request) -> c.VoiceProfile:
    media_repo = media_repository(request)
    if media_repo is not None:
        provider_voice = _provider_voice_build(
            payload.provider_profile_id,
            request,
            operation="design",
            display_name=payload.display_name,
            source="designed",
            input_payload={"prompt": payload.prompt},
        )
        if provider_voice is not None:
            return persist_provider_voice(media_repo, provider_voice)
        resolved = _voice_tts_profile_id(payload.provider_profile_id)
        return media_repo.design_voice(payload.model_copy(update={"provider_profile_id": resolved}))
    provider_voice = _provider_voice_build(
        payload.provider_profile_id,
        request,
        operation="design",
        display_name=payload.display_name,
        source="designed",
        input_payload={"prompt": payload.prompt},
    )
    if provider_voice is not None:
        return provider_voice
    voice = c.VoiceProfile(
        id=new_id("voice"),
        display_name=payload.display_name,
        source="designed",
        provider_profile_id=_voice_tts_profile_id(payload.provider_profile_id),
    )
    repository(request).voices[voice.id] = voice
    return voice


def _provider_voice_build(
    provider_profile_id: str | None,
    request: Request,
    *,
    operation: str,
    display_name: str,
    source: str,
    input_payload: dict,
    before_invoke=None,
) -> c.VoiceProfile | None:
    if not provider_profile_id:
        return None
    repo = repository(request)
    profile = _tts_provider_profile(provider_profile_id, request, missing_ok=False)
    if profile is None:
        return None
    if profile.capability != "tts.speech":
        raise NodeExecutionError(c.ErrorCode.provider_unsupported_option, "Voice provider profile is invalid.")
    if before_invoke is not None:
        before_invoke(repo)
    invocation, result = request.app.state.provider_gateway.invoke(
        ProviderCall(
            provider_profile_id=profile.id,
            capability_id="tts.speech",
            input={"operation": operation, "display_name": display_name, **input_payload},
        )
    )
    if result is None or invocation.error:
        raise NodeExecutionError(
            invocation.error.code if invocation.error else c.ErrorCode.provider_remote_failed,
            invocation.error.message if invocation.error else "Voice provider failed.",
        )
    voice_id = str(result.output.get("voice_id") or new_id("voice"))
    preview_artifact_id = result.output.get("preview_audio_artifact_id")
    voice = c.VoiceProfile(
        id=voice_id,
        display_name=display_name,
        source=source,
        provider_profile_id=profile.id,
        preview_artifact_id=preview_artifact_id if isinstance(preview_artifact_id, str) else None,
    )
    repo.voices[voice.id] = voice
    return voice


def voice_preview(voice_id: str, payload: c.VoicePreviewRequest, request: Request) -> c.VoicePreviewResponse:
    media_repo = media_repository(request)
    if media_repo is not None:
        voice = load_voice(media_repo, voice_id)
        if voice is not None:
            response = _provider_voice_preview(voice, payload, request)
            if response is not None:
                artifact = repository(request).artifacts.get(response.audio_artifact.artifact_id)
                if artifact is not None:
                    artifact_ref = persist_provider_preview(media_repo, voice_id, artifact)
                    return response.model_copy(update={"audio_artifact": artifact_ref})
                return response
            # Voice exists but no real TTS produced a preview: fail loudly instead of
            # fabricating a sandbox:// preview artifact with a synthetic duration.
            if not sandbox_fallback_allowed():
                raise NodeExecutionError(
                    c.ErrorCode.provider_unsupported_option,
                    "未配置真实 TTS 供应商，无法生成音色试听。请先在「设置」中配置并启用真实 TTS 供应商及密钥。",
                )
        response = media_repo.preview_voice(voice_id, payload)
        if response is None:
            raise NodeExecutionError(c.ErrorCode.validation_missing_voice, "Voice not found.")
        return response
    if voice_id not in repository(request).voices:
        raise NodeExecutionError(c.ErrorCode.validation_missing_voice, "Voice not found.")
    repo = repository(request)
    voice = repo.voices[voice_id]
    response = _provider_voice_preview(voice, payload, request)
    if response is not None:
        return response
    if not sandbox_fallback_allowed():
        raise NodeExecutionError(
            c.ErrorCode.provider_unsupported_option,
            "未配置真实 TTS 供应商，无法生成音色试听。请先在「设置」中配置并启用真实 TTS 供应商及密钥。",
        )
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


def _provider_voice_preview(
    voice: c.VoiceProfile,
    payload: c.VoicePreviewRequest,
    request: Request,
) -> c.VoicePreviewResponse | None:
    repo = repository(request)
    voice_id = voice.id
    provider_profile_id = payload.provider_profile_id or voice.provider_profile_id
    profile = _tts_provider_profile(provider_profile_id, request, missing_ok=True)
    if profile is not None:
        invocation, result = request.app.state.provider_gateway.invoke(
            ProviderCall(
                provider_profile_id=profile.id,
                capability_id="tts.speech",
                input={"text": payload.text, "voice_id": voice_id},
            )
        )
        if result is None or invocation.error:
            raise NodeExecutionError(
                invocation.error.code if invocation.error else c.ErrorCode.provider_remote_failed,
                invocation.error.message if invocation.error else "Voice preview provider failed.",
            )
        artifact_id = result.output.get("audio_artifact_id")
        if isinstance(artifact_id, str) and artifact_id in repo.artifacts:
            repo.voices[voice_id] = voice.model_copy(
                update={"preview_artifact_id": artifact_id, "updated_at": c.utcnow()}
            )
            artifact = repo.artifacts[artifact_id]
            duration = (
                float(artifact.media_info.duration_sec)
                if artifact.media_info and artifact.media_info.duration_sec
                else float(result.output.get("duration_sec") or result.audio_seconds or 0)
            )
            return c.VoicePreviewResponse(
                voice_id=voice_id,
                audio_artifact=repo.artifact_ref(artifact_id),
                duration_sec=duration,
            )
    return None


def _tts_provider_profile(provider_profile_id: str | None, request: Request, *, missing_ok: bool):
    if not provider_profile_id:
        return None
    gateway = request.app.state.provider_gateway
    profile = None
    reader = getattr(gateway, "provider_reader", None)
    if reader is not None:
        profile = reader.get_profile(provider_profile_id)
    if profile is None:
        profile = repository(request).provider_profiles.get(provider_profile_id)
    if profile is None:
        if missing_ok:
            return None
        raise NodeExecutionError(c.ErrorCode.provider_unsupported_option, "Voice provider profile is invalid.")
    if profile.capability != "tts.speech":
        raise NodeExecutionError(c.ErrorCode.provider_unsupported_option, "Voice provider profile is invalid.")
    if not profile.enabled:
        return None
    if profile.provider_id not in gateway.plugins:
        return None
    if profile.secret_ref and not gateway._secret_is_active(profile.secret_ref):
        return None
    return profile


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
