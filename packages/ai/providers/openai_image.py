"""OpenAI-compatible image generation provider (capability ``image.generate``).

Faithful port of the origin ``OpenAIImageAdapter`` (digital-human-Cutagent
``app/ai/adapters/openai_image.py``): a single ``POST {base_url}/images/generations``
call against an OpenAI-compatible image endpoint (OpenAI ``gpt-image`` or the
neuromash mirror ``gpt-image-2-all``), with the neuromash param-narrowing the
origin applies, and the same ``data[0].b64_json`` -> ``data[0].url`` response
fallback. The decoded PNG bytes are stored as a ``cover.image`` artifact.

This is the PAID path. It is only ever reached through the gateway when an
enabled real ``image.generate`` ProviderProfile + active secret exist (see
``ProviderGateway._validate_profile`` and the cover node's gating). Without that
configuration the cover node never constructs a ProviderCall for it, so no
network call and no spend happen.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import mimetypes
import time
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from packages.ai.gateway.provider_context import ProviderInvocationContext
from packages.ai.gateway.provider_gateway import (
    ProviderCall,
    ProviderResult,
    ProviderRuntimeError,
)
from packages.ai.providers._volc_sigv4 import signed_headers as volc_signed_headers
from packages.ai.providers.common import money_cny, option, request, require_secret, response_json
from packages.core.contracts import ArtifactKind, ErrorCode
from packages.media.cover_image import normalize_cover_image_bytes

NEUROMASH_MIRROR_MODEL = "gpt-image-2-all"
ARK_DEFAULT_REGION = "cn-beijing"
ARK_SERVICE = "ark"
ARK_OPENAPI_HOST = "ark.cn-beijing.volcengineapi.com"
ARK_OPENAPI_VERSION = "2024-01-01"
ARK_TEMPORARY_API_KEY_TTL_SECONDS = 604800
_OPENAPI_AUTH_ERROR_CODES = frozenset(
    {
        "AccessDenied",
        "AuthenticationError",
        "Forbidden",
        "InvalidAccessKey",
        "InvalidCredential",
        "InvalidSecurityToken",
        "MissingAuthenticationToken",
        "NoPermission",
        "SignatureDoesNotMatch",
    }
)


class OpenAIImageProvider:
    provider_id = "openai.image"
    # Origin fixed catalog: image:gpt-image-2[-all] = 0.4 CNY / image.
    cost_per_image = Decimal("0.4")

    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def invoke_with_context(
        self, call: ProviderCall, context: ProviderInvocationContext
    ) -> ProviderResult:
        if call.capability_id != "image.generate":
            raise ProviderRuntimeError(
                ErrorCode.provider_unsupported_option,
                f"OpenAI image provider cannot run {call.capability_id}.",
            )
        api_key = self._api_key(context)
        prompt = str(call.input.get("prompt") or "").strip()
        if not prompt:
            raise ProviderRuntimeError(ErrorCode.provider_unsupported_option, "Image prompt is required.")
        base_url = str(option(context, "base_url", "https://api.openai.com/v1")).rstrip("/")
        model_id = context.profile.model_id
        size = str(call.input.get("size") or option(context, "size", "1024x1536"))
        count = int(call.input.get("n") or option(context, "n", 1) or 1)
        reference_b64 = str(
            call.input.get("reference_image_b64") or call.input.get("template_image_b64") or ""
        ).strip()
        reference_requested = bool(reference_b64)
        reference_used = False
        reference_transport: str | None = None
        result: dict[str, Any] | None = None
        if reference_b64:
            # Reference-image path: edit from an uploaded cover template, a selected
            # source video frame, or a combined reference board. Falls back to plain
            # generation if the endpoint/model does not support edits.
            self._record_reference_request_artifact(
                call,
                context,
                reference_b64=reference_b64,
                reference_filename=str(
                    call.input.get("reference_filename")
                    or call.input.get("template_filename")
                    or "cover-reference.png"
                ),
            )
            result = self._edit_with_reference(
                base_url,
                api_key,
                prompt,
                reference_b64=reference_b64,
                reference_filename=str(
                    call.input.get("reference_filename")
                    or call.input.get("template_filename")
                    or "cover-reference.png"
                ),
                size=size,
                count=count,
                model_id=model_id,
                context=context,
            )
            reference_used = result is not None
            if reference_used:
                reference_transport = str(result.pop("_reference_transport", "images.edits"))
        if result is None:
            payload = self._generation_payload(model_id, prompt, size=size, count=count, context=context)
            response = request(
                self.client,
                "POST",
                f"{base_url}/images/generations",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json_body=payload,
                timeout=float(context.profile.timeout_sec),
            )
            result = response_json(response)
        image_bytes, output_format = self._decode_image(result, api_key, context)
        try:
            image_bytes = normalize_cover_image_bytes(image_bytes)
        except ValueError as exc:
            raise ProviderRuntimeError(
                ErrorCode.provider_remote_failed,
                "Image provider returned a cover that could not be normalized to 9:16.",
            ) from exc
        output_format = "png"
        artifact = context.store_media_bytes(
            content=image_bytes,
            filename=f"{call.idempotency_key or 'ai-cover'}.{output_format}",
            purpose="covers",
            kind=ArtifactKind.cover_image,
            call=call,
        )
        return ProviderResult(
            output={
                "cover_artifact_id": artifact.id,
                "cover_uri": artifact.uri,
                "model": model_id,
                "size": size,
                "reference_image_requested": reference_requested,
                "reference_image_used": reference_used,
                "reference_transport": reference_transport,
            },
            image_count=count,
            provider_credits=self.cost_per_image * Decimal(count),
            estimated_cost=money_cny(self.cost_per_image * Decimal(count)),
            raw_usage=result.get("usage") if isinstance(result.get("usage"), dict) else {},
        )

    def _generation_payload(
        self,
        model_id: str,
        prompt: str,
        *,
        size: str,
        count: int,
        context: ProviderInvocationContext,
    ) -> dict[str, Any]:
        # Neuromash mirror only honours size/n; OpenAI accepts quality/output_format.
        if model_id == NEUROMASH_MIRROR_MODEL or str(option(context, "provider_kind", "")) == "neuromash":
            return {"model": model_id, "prompt": prompt, "size": size, "n": count}
        payload: dict[str, Any] = {"model": model_id, "prompt": prompt, "size": size, "n": count}
        quality = option(context, "quality")
        if quality:
            payload["quality"] = str(quality)
        output_format = option(context, "output_format")
        if output_format:
            payload["output_format"] = str(output_format)
        response_format = option(context, "response_format")
        if response_format:
            payload["response_format"] = str(response_format)
        watermark = option(context, "watermark")
        if watermark is not None:
            payload["watermark"] = _bool_option(watermark)
        return payload

    def _api_key(self, context: ProviderInvocationContext) -> str:
        return require_secret(context)

    def _record_reference_request_artifact(
        self,
        call: ProviderCall,
        context: ProviderInvocationContext,
        *,
        reference_b64: str,
        reference_filename: str,
    ) -> None:
        reference_bytes = _reference_image_bytes(reference_b64)
        if not reference_bytes:
            return
        artifact = context.store_media_bytes(
            content=reference_bytes,
            filename=_clean_filename(reference_filename, "cover-reference.png"),
            purpose="provider-requests",
            kind=ArtifactKind.provider_raw_request,
            call=call,
        )
        context.update_invocation(updates={"request_artifact_id": artifact.id})

    def _edit_with_reference(
        self,
        base_url: str,
        api_key: str,
        prompt: str,
        *,
        reference_b64: str,
        reference_filename: str,
        size: str,
        count: int,
        model_id: str,
        context: ProviderInvocationContext,
    ) -> dict[str, Any] | None:
        """POST the prompt + reference image to ``/images/edits`` so a cover
        template and/or source frame conditions the result. Returns decoded JSON, or
        ``None`` to signal text-to-image fallback when the endpoint/model rejects
        edits, e.g. HTTP 400/404/422."""
        reference_bytes = _reference_image_bytes(reference_b64)
        if not reference_bytes:
            return None
        mime = mimetypes.guess_type(reference_filename)[0] or "image/png"
        data = {"model": model_id, "prompt": prompt, "size": size, "n": str(count)}
        response_format = option(context, "response_format")
        if response_format:
            data["response_format"] = str(response_format)
        watermark = option(context, "watermark")
        if watermark is not None:
            data["watermark"] = "true" if _bool_option(watermark) else "false"
        # Try the canonical ``image`` field first, then ``image[]`` (some mirrors
        # only accept the array form) — mirrors the origin's two-field attempt.
        for image_field in ("image", "image[]"):
            try:
                response = request(
                    self.client,
                    "POST",
                    f"{base_url}/images/edits",
                    headers={"Authorization": f"Bearer {api_key}"},
                    data=data,
                    files={image_field: (reference_filename, reference_bytes, mime)},
                    timeout=float(context.profile.timeout_sec),
                )
            except ProviderRuntimeError as exc:
                # auth/quota are hard failures (re-raise); request-shape/endpoint
                # rejections fall back to generation so the cover still ships.
                if exc.code in {ErrorCode.provider_auth_failed, ErrorCode.provider_quota_exceeded}:
                    raise
                continue
            return response_json(response)
        return None

    def _decode_image(
        self, result: dict[str, Any], api_key: str, context: ProviderInvocationContext
    ) -> tuple[bytes, str]:
        data = result.get("data")
        first = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else {}
        b64_image = str(first.get("b64_json") or "").strip()
        if b64_image:
            return self._b64_to_bytes(b64_image), "png"
        url = str(first.get("url") or "").strip()
        if url:
            return self._url_to_bytes(url, api_key, context), "png"
        raise ProviderRuntimeError(ErrorCode.provider_remote_failed, "Image provider returned no image data.")

    @staticmethod
    def _b64_to_bytes(b64_image: str) -> bytes:
        if b64_image.startswith("data:") and ";base64," in b64_image:
            b64_image = b64_image.split(";base64,", 1)[1].strip()
        try:
            return base64.b64decode(b64_image)
        except (binascii.Error, ValueError) as exc:
            raise ProviderRuntimeError(ErrorCode.provider_remote_failed, "Image provider returned invalid base64.") from exc

    def _url_to_bytes(self, url: str, api_key: str, context: ProviderInvocationContext) -> bytes:
        if url.startswith("data:") and ";base64," in url:
            return self._b64_to_bytes(url)
        return request(
            self.client,
            "GET",
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=float(context.profile.timeout_sec),
        ).content


class ArkSeedreamImageProvider(OpenAIImageProvider):
    """Volcengine Ark Seedream image provider.

    Ark's image endpoint is OpenAI-compatible, so this adapter intentionally
    reuses the same REST implementation while keeping the provider id distinct
    for routing, secrets, cost reports, and balance grouping. When the configured
    secret is an Ark AK/SK pair, it first exchanges that pair for a temporary
    OpenAI-compatible API key through Ark OpenAPI ``GetApiKey``.
    """

    provider_id = "volcengine.seedream"

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self._api_key_cache: dict[str, tuple[str, float]] = {}

    def _api_key(self, context: ProviderInvocationContext) -> str:
        secret = require_secret(context)
        if not self._use_access_key_auth(secret, context):
            return secret
        resource_type, resource_id, project_name = self._api_key_resource(context)
        return self._temporary_api_key(
            context,
            secret,
            resource_type=resource_type,
            resource_id=resource_id,
            project_name=project_name,
            timeout=float(context.profile.timeout_sec),
        )

    @staticmethod
    def _auth_type(context: ProviderInvocationContext) -> str:
        return str(option(context, "auth_type", "auto") or "auto").strip().lower()

    @staticmethod
    def _use_access_key_auth(secret: str, context: ProviderInvocationContext) -> bool:
        auth_type = ArkSeedreamImageProvider._auth_type(context)
        if auth_type in {"api_key", "bearer"}:
            return False
        if auth_type in {"access_key", "signed"}:
            return True
        access_key_id, _, secret_access_key = secret.partition(":")
        return bool(access_key_id and secret_access_key)

    @staticmethod
    def _api_key_resource(context: ProviderInvocationContext) -> tuple[str, str, str | None]:
        configured = str(
            option(context, "endpoint_id", "")
            or option(context, "ark_endpoint_id", "")
            or ""
        ).strip()
        if configured:
            return "endpoint", configured, None
        model_id = str(context.profile.model_id or "").strip()
        if model_id.startswith("ep-"):
            return "endpoint", model_id, None
        if not model_id:
            raise ProviderRuntimeError(
                ErrorCode.provider_unsupported_option,
                "Volcengine Ark AK/SK auth requires profile.model_id.",
            )
        project_name = str(option(context, "project_name", "default") or "default").strip()
        return "presetendpoint", model_id, project_name

    def _edit_with_reference(
        self,
        base_url: str,
        api_key: str,
        prompt: str,
        *,
        reference_b64: str,
        reference_filename: str,
        size: str,
        count: int,
        model_id: str,
        context: ProviderInvocationContext,
    ) -> dict[str, Any] | None:
        """Seedream 5.0 reference images ride on ``/images/generations``.

        Ark's OpenAI-compatible Seedream API exposes reference input as the JSON
        ``image`` field on the generation endpoint rather than the OpenAI
        ``/images/edits`` endpoint.
        """
        image_value = _image_data_uri(reference_b64, reference_filename)
        if image_value is None:
            return None
        payload = self._generation_payload(model_id, prompt, size=size, count=count, context=context)
        payload["image"] = image_value
        response = request(
            self.client,
            "POST",
            f"{base_url}/images/generations",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json_body=payload,
            timeout=float(context.profile.timeout_sec),
        )
        result = response_json(response)
        result["_reference_transport"] = "images.generations.image"
        return result

    def _temporary_api_key(
        self,
        context: ProviderInvocationContext,
        secret: str,
        *,
        resource_type: str,
        resource_id: str,
        project_name: str | None,
        timeout: float,
    ) -> str:
        ttl = int(
            option(
                context,
                "temporary_api_key_ttl_seconds",
                ARK_TEMPORARY_API_KEY_TTL_SECONDS,
            )
            or ARK_TEMPORARY_API_KEY_TTL_SECONDS
        )
        secret_hash = hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]
        cache_key = f"{secret_hash}:{resource_type}:{resource_id}:{project_name or ''}:{ttl}"
        cached = self._api_key_cache.get(cache_key)
        now = time.time()
        if cached and cached[1] > now + 60:
            return cached[0]
        body: dict[str, Any] = {
            "DurationSeconds": ttl,
            "ResourceType": resource_type,
            "ResourceIds": [resource_id],
        }
        if project_name is not None:
            body["ProjectName"] = project_name
        result = self._ark_openapi_call(
            context,
            secret,
            action="GetApiKey",
            body=body,
            timeout=timeout,
        )
        api_key = str(result.get("ApiKey") or "").strip()
        if not api_key:
            raise ProviderRuntimeError(
                ErrorCode.provider_auth_failed,
                "Volcengine Ark GetApiKey response missing ApiKey.",
            )
        expires_at = now + ttl
        try:
            expired_time = float(result.get("ExpiredTime") or 0)
        except (TypeError, ValueError):
            expired_time = 0
        if expired_time > now:
            expires_at = expired_time
        self._api_key_cache[cache_key] = (api_key, expires_at)
        return api_key

    def _ark_openapi_call(
        self,
        context: ProviderInvocationContext,
        secret: str,
        *,
        action: str,
        body: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        access_key_id, _, secret_access_key = secret.partition(":")
        if not access_key_id or not secret_access_key:
            raise ProviderRuntimeError(
                ErrorCode.provider_auth_failed,
                "Volcengine Ark OpenAPI auth requires 'access_key_id:secret_access_key'.",
            )
        url = f"https://{ARK_OPENAPI_HOST}/?Action={action}&Version={ARK_OPENAPI_VERSION}"
        raw_body = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = volc_signed_headers(
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            method="POST",
            url=url,
            body=raw_body,
            region=str(option(context, "ark_region", ARK_DEFAULT_REGION) or ARK_DEFAULT_REGION),
            service=ARK_SERVICE,
        )
        headers["Content-Type"] = "application/json"
        try:
            response = self.client.post(url, headers=headers, content=raw_body, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise ProviderRuntimeError(ErrorCode.provider_timeout, "Provider request timed out.") from exc
        except httpx.HTTPError as exc:
            raise ProviderRuntimeError(ErrorCode.provider_remote_failed, str(exc)) from exc
        if response.status_code in (401, 403):
            raise ProviderRuntimeError(
                ErrorCode.provider_auth_failed,
                f"Volcengine Ark OpenAPI {action} auth failed (HTTP {response.status_code}).",
            )
        payload = response_json(response)
        error = (
            (payload.get("ResponseMetadata") or {}).get("Error")
            if isinstance(payload, dict)
            else None
        )
        if error:
            code = str(error.get("Code") or "unknown")
            if code in _OPENAPI_AUTH_ERROR_CODES:
                raise ProviderRuntimeError(
                    ErrorCode.provider_auth_failed,
                    f"Volcengine Ark OpenAPI {action} auth failed (Code={code}).",
                )
            if code.startswith("InvalidParameter.ResourceIds"):
                raise ProviderRuntimeError(
                    ErrorCode.provider_unsupported_option,
                    f"Volcengine Ark resource id is invalid for {action} (Code={code}).",
                )
            if code.startswith("InvalidParameter.ProjectName"):
                raise ProviderRuntimeError(
                    ErrorCode.provider_unsupported_option,
                    f"Volcengine Ark project_name is invalid for {action} (Code={code}).",
                )
            raise ProviderRuntimeError(
                ErrorCode.provider_remote_failed,
                f"Volcengine Ark OpenAPI {action} failed (Code={code}).",
            )
        result = payload.get("Result") if isinstance(payload, dict) else None
        return result if isinstance(result, dict) else {}


def _bool_option(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _image_data_uri(reference_b64: str, filename: str) -> str | None:
    value = str(reference_b64 or "").strip()
    if not value:
        return None
    if value.startswith("data:"):
        return value
    if _reference_image_bytes(value) is None:
        return None
    mime = mimetypes.guess_type(_clean_filename(filename, "reference.png"))[0] or "image/png"
    return f"data:{mime};base64,{value}"


def _reference_image_bytes(reference_b64: str) -> bytes | None:
    value = str(reference_b64 or "").strip()
    if not value:
        return None
    if value.startswith("data:") and ";base64," in value:
        value = value.split(";base64,", 1)[1].strip()
    elif value.startswith("data:"):
        return None
    value = "".join(value.split())
    try:
        data = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None
    return data or None


def _clean_filename(value: str, fallback: str) -> str:
    parsed = urlparse(str(value or ""))
    candidate = Path(parsed.path).name if parsed.scheme else Path(str(value or "")).name
    return candidate or fallback
