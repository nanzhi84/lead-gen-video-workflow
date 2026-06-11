from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError

from apps.api.dependencies import (
    authenticate_api_request,
    http_exception_handler,
    node_error_handler,
    request_validation_error_handler,
)
from apps.api.routers import (
    auth,
    case_agent,
    cases,
    core,
    finished_videos,
    imports,
    jobs_runs,
    media,
    ops,
    prompts,
    providers,
    publishing,
    secrets,
    uploads,
    voices,
)
from packages.ai.gateway import ProviderGateway, SqlAlchemyProviderRepository, SqlAlchemyProviderRuntimeRepository
from packages.ai.prompts import PromptRegistry, SqlAlchemyPromptRepository, SqlAlchemyPromptRuntimeRepository
from packages.core.auth import AuthService, create_sqlalchemy_auth_service
from packages.core.auth.service import create_password_hasher
from packages.core.storage import Repository, get_object_store
from packages.core.storage.bootstrap import (
    bootstrap_sqlalchemy_storage_if_enabled,
    get_sqlalchemy_session_factory_if_enabled,
)
from packages.core.storage.secret_store import LocalSecretStore
from packages.core.storage.sqlalchemy_idempotency import SqlAlchemyIdempotencyRepository
from packages.core.storage.sqlalchemy_secrets import SqlAlchemySecretRepository
from packages.core.storage.sqlalchemy_uploads import SqlAlchemyUploadRepository
from packages.core.workflow import NodeExecutionError
from packages.creative.cases import SqlAlchemyCaseLearningRepository, SqlAlchemyCaseRepository
from packages.media import SqlAlchemyMediaRepository
from packages.ops import SqlAlchemyOpsRepository
from packages.production import SqlAlchemyProductionRepository
from packages.production.pipeline import build_digital_human_workflow
from packages.publishing import SqlAlchemyPublishingRepository

ROUTER_MODULES = (
    core,
    auth,
    uploads,
    secrets,
    cases,
    jobs_runs,
    media,
    voices,
    prompts,
    providers,
    case_agent,
    finished_videos,
    publishing,
    ops,
    imports,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap_sqlalchemy_storage_if_enabled()
    session_factory = get_sqlalchemy_session_factory_if_enabled()
    configure_app_state(app, session_factory=session_factory)
    yield


def configure_app_state(app: FastAPI, *, session_factory=None) -> None:
    runtime_repository = Repository()
    app.state.repository = runtime_repository
    app.state.object_store = get_object_store()
    app.state.secret_store = LocalSecretStore()
    if session_factory is None:
        app.state.sqlalchemy_case_repository = None
        app.state.sqlalchemy_case_learning_repository = None
        app.state.sqlalchemy_upload_repository = None
        app.state.sqlalchemy_media_repository = None
        app.state.sqlalchemy_prompt_repository = None
        app.state.sqlalchemy_provider_repository = None
        app.state.sqlalchemy_idempotency_repository = None
        app.state.sqlalchemy_secret_repository = None
        app.state.sqlalchemy_ops_repository = None
        app.state.sqlalchemy_publishing_repository = None
        app.state.sqlalchemy_production_repository = None
        app.state.auth_service = AuthService(runtime_repository, create_password_hasher())
        provider_reader = None
        prompt_reader = None
    else:
        app.state.sqlalchemy_case_repository = SqlAlchemyCaseRepository(session_factory)
        app.state.sqlalchemy_case_learning_repository = SqlAlchemyCaseLearningRepository(session_factory)
        app.state.sqlalchemy_upload_repository = SqlAlchemyUploadRepository(session_factory)
        app.state.sqlalchemy_media_repository = SqlAlchemyMediaRepository(session_factory)
        app.state.sqlalchemy_prompt_repository = SqlAlchemyPromptRepository(session_factory)
        app.state.sqlalchemy_provider_repository = SqlAlchemyProviderRepository(session_factory)
        app.state.sqlalchemy_idempotency_repository = SqlAlchemyIdempotencyRepository(session_factory)
        app.state.sqlalchemy_secret_repository = SqlAlchemySecretRepository(session_factory, app.state.secret_store)
        app.state.sqlalchemy_ops_repository = SqlAlchemyOpsRepository(session_factory)
        app.state.sqlalchemy_publishing_repository = SqlAlchemyPublishingRepository(session_factory)
        app.state.sqlalchemy_production_repository = SqlAlchemyProductionRepository(session_factory)
        app.state.auth_service = create_sqlalchemy_auth_service(session_factory)
        provider_reader = SqlAlchemyProviderRuntimeRepository(session_factory)
        prompt_reader = SqlAlchemyPromptRuntimeRepository(session_factory)
    app.state.provider_gateway = ProviderGateway(
        runtime_repository,
        provider_reader=provider_reader,
        secret_store=app.state.secret_store,
    )
    app.state.prompt_registry = PromptRegistry(runtime_repository, prompt_reader=prompt_reader)
    app.state.workflow = build_digital_human_workflow(
        runtime_repository,
        provider_gateway=app.state.provider_gateway,
        prompt_registry=app.state.prompt_registry,
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title="Cutagent Clean-Slate API",
        version="0.1.0",
        description="Case-first digital human production API generated from the clean-slate spec.",
        lifespan=lifespan,
    )
    configure_app_state(app)
    app.add_exception_handler(NodeExecutionError, node_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.middleware("http")(authenticate_api_request)
    for router_module in ROUTER_MODULES:
        app.include_router(router_module.router)
    return app
