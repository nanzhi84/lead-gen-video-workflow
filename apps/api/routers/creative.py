from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from apps.api.common import object_store, provider_repository, repository, secret_store
from apps.api.dependencies import require_role
from packages.ai.gateway import ProviderCall
from packages.core import contracts as c
from packages.core.workflow import NodeExecutionError
from packages.creative.reference_extract import ReferenceExtractError, extract_reference

router = APIRouter()


@router.post("/api/creative/reference-extract", response_model=c.ReferenceExtractResult)
async def reference_extract(payload: c.ReferenceExtractRequest, request: Request) -> c.ReferenceExtractResult:
    require_role(request, c.UserRole.operator)
    try:
        return await extract_reference(
            payload.url,
            payload.language,
            asr_invoke=lambda audio_url, language: _invoke_asr(request, audio_url, language),
            object_store=object_store(request),
            secret_store=secret_store(request),
        )
    except ReferenceExtractError as exc:
        raise NodeExecutionError(exc.code, exc.message, details=exc.details) from exc


def _invoke_asr(request: Request, audio_url: str, language: str) -> str:
    profile = _first_asr_profile(request)
    if profile is None:
        raise ReferenceExtractError(c.ErrorCode.reference_asr_failed, "ASR provider profile is not configured.")
    invocation, result = request.app.state.provider_gateway.invoke(
        ProviderCall(
            provider_profile_id=profile.id,
            capability_id="asr.transcribe",
            input={"audio_uri": audio_url, "language_hints": [language]},
        )
    )
    if result is None or invocation.error:
        details: dict[str, Any] = {"provider_invocation_id": invocation.id}
        if invocation.error is not None:
            code = invocation.error.code.value if hasattr(invocation.error.code, "value") else str(invocation.error.code)
            details["provider_error_code"] = code
        raise ReferenceExtractError(
            c.ErrorCode.reference_asr_failed,
            invocation.error.message if invocation.error else "ASR provider failed.",
            details=details,
        )
    text = result.output.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ReferenceExtractError(c.ErrorCode.reference_asr_failed, "ASR response did not include text.")
    return text.strip()


def _first_asr_profile(request: Request) -> c.ProviderProfile | None:
    db_repo = provider_repository(request)
    if db_repo is not None:
        profiles = db_repo.list_profiles(capability="asr.transcribe", limit=20)
    else:
        profiles = [profile for profile in repository(request).provider_profiles.values() if profile.capability == "asr.transcribe"]
    for profile in profiles:
        if profile.enabled:
            return profile
    return None
