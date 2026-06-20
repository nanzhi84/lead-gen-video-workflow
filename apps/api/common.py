from __future__ import annotations

from contextvars import ContextVar
from uuid import uuid4

from fastapi import Request

from packages.ai.gateway import SqlAlchemyProviderRepository
from packages.ai.prompts import SqlAlchemyPromptRepository
from packages.core import contracts as c
from packages.core.auth import AuthService, SqlAlchemyAuthService
from packages.core.storage import ObjectStore, Repository
from packages.core.storage.secret_store import SecretStore
from packages.core.storage.sqlalchemy_idempotency import SqlAlchemyIdempotencyRepository
from packages.core.storage.sqlalchemy_secrets import SqlAlchemySecretRepository
from packages.core.storage.sqlalchemy_uploads import SqlAlchemyUploadRepository
from packages.core.workflow import NodeExecutionError, WorkflowRuntimeAdapter
from packages.creative.cases import (
    SqlAlchemyCaseLearningRepository,
    SqlAlchemyCaseRepository,
    SqlAlchemyCaseRubricRepository,
)
from packages.media import SqlAlchemyMediaRepository
from packages.ops import SqlAlchemyOpsRepository
from packages.production import SqlAlchemyProductionRepository
from packages.publishing import SqlAlchemyAccountsRepository, SqlAlchemyPublishingRepository
from packages.publishing.connectors.xiaovmao_cdp import XiaoVmaoLoginManager

REQUEST_ID_CONTEXT: ContextVar[str | None] = ContextVar("request_id", default=None)


def request_id() -> str:
    current = REQUEST_ID_CONTEXT.get()
    if current is not None:
        return current
    return f"req_{uuid4().hex[:12]}"


def repository(request: Request) -> Repository:
    return request.app.state.repository


def object_store(request: Request) -> ObjectStore:
    return request.app.state.object_store


def settings(request: Request):
    return request.app.state.settings


def secret_store(request: Request) -> SecretStore:
    return request.app.state.secret_store


def auth(request: Request) -> AuthService | SqlAlchemyAuthService:
    return request.app.state.auth_service


def workflow_runtime(request: Request) -> WorkflowRuntimeAdapter:
    return request.app.state.workflow


def case_repository(request: Request) -> SqlAlchemyCaseRepository | None:
    return request.app.state.sqlalchemy_case_repository


def case_learning_repository(request: Request) -> SqlAlchemyCaseLearningRepository | None:
    return request.app.state.sqlalchemy_case_learning_repository


def case_rubric_repository(request: Request) -> SqlAlchemyCaseRubricRepository | None:
    return request.app.state.sqlalchemy_case_rubric_repository


def upload_repository(request: Request) -> SqlAlchemyUploadRepository | None:
    return request.app.state.sqlalchemy_upload_repository


def media_repository(request: Request) -> SqlAlchemyMediaRepository | None:
    return request.app.state.sqlalchemy_media_repository


def prompt_repository(request: Request) -> SqlAlchemyPromptRepository | None:
    return request.app.state.sqlalchemy_prompt_repository


def provider_repository(request: Request) -> SqlAlchemyProviderRepository | None:
    return request.app.state.sqlalchemy_provider_repository


def idempotency_repository(request: Request) -> SqlAlchemyIdempotencyRepository | None:
    return request.app.state.sqlalchemy_idempotency_repository


def secret_repository(request: Request) -> SqlAlchemySecretRepository | None:
    return request.app.state.sqlalchemy_secret_repository


def ops_repository(request: Request) -> SqlAlchemyOpsRepository | None:
    return request.app.state.sqlalchemy_ops_repository


def publishing_repository(request: Request) -> SqlAlchemyPublishingRepository | None:
    return request.app.state.sqlalchemy_publishing_repository


def accounts_repository(request: Request) -> SqlAlchemyAccountsRepository | None:
    return request.app.state.sqlalchemy_accounts_repository


def xiaovmao_login_manager(request: Request) -> XiaoVmaoLoginManager:
    return request.app.state.xiaovmao_login_manager


def production_repository(request: Request) -> SqlAlchemyProductionRepository | None:
    return request.app.state.sqlalchemy_production_repository


def page(items, limit: int = 50):
    values = list(items)[:limit]
    return c.PageResponse(items=values, total_hint=len(values), request_id=request_id())


def get_case(request: Request, case_id: str) -> c.CaseDetail:
    repo = case_repository(request)
    if repo is not None:
        case = repo.get_case(case_id)
        if case is not None:
            return case
    runtime_repo = repository(request)
    if case_id not in runtime_repo.cases:
        raise NodeExecutionError(c.ErrorCode.validation_missing_case, f"Case {case_id} does not exist.")
    return runtime_repo.cases[case_id]


def signed(request: Request, path: str) -> c.SignedUrlResponse:
    return object_store(request).signed_url(f"local://cutagent-local/{path}").model_copy(
        update={"request_id": request_id()}
    )


def ensure_artifact_ref(request: Request, artifact_id: str) -> c.ArtifactRef:
    runtime_repo = repository(request)
    if artifact_id not in runtime_repo.artifacts:
        raise NodeExecutionError(c.ErrorCode.artifact_missing, f"Artifact {artifact_id} does not exist.")
    return runtime_repo.artifact_ref(artifact_id)
