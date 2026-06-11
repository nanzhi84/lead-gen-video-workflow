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

def list_secrets(request: Request, limit: int = 50) -> c.PageResponse[c.SecretPreview]:
    if secret_repository(request) is not None:
        values = secret_repository(request).list_secrets(limit=limit)
        return c.PageResponse(items=values, total_hint=len(values), request_id=request_id())
    return page(repository(request).secrets.values(), limit)


def create_secret(payload: c.CreateSecretRequest, request: Request) -> c.SecretPreview:
    if secret_repository(request) is not None:
        return secret_repository(request).create_secret(payload)
    secret = c.SecretPreview(
        id=new_id("sec"),
        provider_id=payload.provider_id,
        environment=payload.environment,
        name=payload.name,
        secret_ref=secret_store(request).put(payload.plaintext_secret, secret_ref=f"{new_id('sec')}.secret"),
    )
    repository(request).secrets[secret.id] = secret
    return secret


def rotate_secret(secret_id: str, payload: c.RotateSecretRequest, request: Request) -> c.SecretPreview:
    if secret_repository(request) is not None:
        return secret_repository(request).rotate_secret(secret_id, payload)
    old_secret = repository(request).secrets[secret_id]
    repository(request).secrets[secret_id] = old_secret.model_copy(
        update={"status": c.SecretStatus.rotated, "rotated_at": c.utcnow(), "updated_at": c.utcnow()}
    )
    new_secret = c.SecretPreview(
        id=new_id("sec"),
        provider_id=old_secret.provider_id,
        environment=old_secret.environment,
        name=old_secret.name,
        secret_ref=secret_store(request).put(payload.plaintext_secret, secret_ref=f"{new_id('sec')}.secret"),
        rotated_from_secret_id=old_secret.id,
    )
    repository(request).secrets[new_secret.id] = new_secret
    return new_secret


def disable_secret(secret_id: str, payload: c.DisableSecretRequest, request: Request) -> c.SecretPreview:
    if secret_repository(request) is not None:
        return secret_repository(request).disable_secret(secret_id, payload)
    secret = repository(request).secrets[secret_id]
    if secret.secret_ref:
        secret_store(request).disable(secret.secret_ref)
    return repository(request).patch(repository(request).secrets, secret_id, {"status": c.SecretStatus.disabled, "disabled_at": c.utcnow()})
