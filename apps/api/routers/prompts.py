from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request, Response, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse

from apps.api.dependencies import require_role
from apps.api.services import prompts as service
from packages.core import contracts as c

router = APIRouter()

@router.get("/api/prompts", response_model=c.PageResponse[c.PromptTemplateView])
def list_prompts(
    request: Request,
    limit: int = 50,
    status: str | None = None,
    purpose: str | None = None,
) -> c.PageResponse[c.PromptTemplateView]:
    return service.list_prompts(request, limit, status, purpose)


@router.post("/api/prompts", response_model=c.PromptTemplateView, status_code=201)
def create_prompt(payload: c.CreatePromptTemplateRequest, request: Request) -> c.PromptTemplateView:
    require_role(request, c.UserRole.admin)
    return service.create_prompt(payload, request)


@router.get("/api/prompts/{template_id}/versions", response_model=c.PageResponse[c.PromptVersionView])
def prompt_versions(request: Request, template_id: str, limit: int = 50) -> c.PageResponse[c.PromptVersionView]:

    return service.prompt_versions(request, template_id, limit)


@router.post(
    "/api/prompts/{template_id}/versions",
    response_model=c.PromptVersionView,
    status_code=201,
)
def create_prompt_version(
    template_id: str, payload: c.CreatePromptVersionRequest, request: Request
) -> c.PromptVersionView:
    require_role(request, c.UserRole.admin)
    return service.create_prompt_version(template_id, payload, request)


@router.post(
    "/api/prompts/{template_id}/versions/{version_id}/approve",
    response_model=c.PromptVersionView,
)
def approve_prompt_version(
    template_id: str, version_id: str, payload: c.ApprovePromptVersionRequest, request: Request
) -> c.PromptVersionView:
    require_role(request, c.UserRole.admin)
    return service.approve_prompt_version(template_id, version_id, payload, request)


@router.post(
    "/api/prompts/{template_id}/versions/{version_id}/publish",
    response_model=c.PromptVersionView,
)
def publish_prompt_version(
    template_id: str, version_id: str, payload: c.PublishPromptVersionRequest, request: Request
) -> c.PromptVersionView:
    require_role(request, c.UserRole.admin)
    return service.publish_prompt_version(template_id, version_id, payload, request)


@router.post("/api/prompts/{template_id}/rollback", response_model=c.PromptVersionView)
def rollback_prompt(
    template_id: str, payload: c.RollbackPromptRequest, request: Request
) -> c.PromptVersionView:
    require_role(request, c.UserRole.admin)
    return service.rollback_prompt(template_id, payload, request)


@router.get("/api/prompts/bindings", response_model=c.PageResponse[c.PromptBindingView])
def prompt_bindings(request: Request, limit: int = 50) -> c.PageResponse[c.PromptBindingView]:

    return service.prompt_bindings(request, limit)


@router.post("/api/prompts/bindings", response_model=c.PromptBindingView, status_code=201)
def create_prompt_binding(payload: c.CreatePromptBindingRequest, request: Request) -> c.PromptBindingView:
    require_role(request, c.UserRole.admin)
    return service.create_prompt_binding(payload, request)


@router.patch("/api/prompts/bindings/{binding_id}", response_model=c.PromptBindingView)
def patch_prompt_binding(
    binding_id: str, payload: c.PatchPromptBindingRequest, request: Request
) -> c.PromptBindingView:
    require_role(request, c.UserRole.admin)
    return service.patch_prompt_binding(binding_id, payload, request)


@router.get("/api/prompts/experiments", response_model=c.PageResponse[c.PromptExperiment])
def prompt_experiments(
    request: Request,
    limit: int = 50,
    prompt_template_id: str | None = None,
    status: str | None = None,
) -> c.PageResponse[c.PromptExperiment]:
    return service.prompt_experiments(request, limit, prompt_template_id, status)


@router.post("/api/prompts/experiments", response_model=c.PromptExperiment, status_code=201)
def create_prompt_experiment(
    payload: c.CreatePromptExperimentRequest, request: Request
) -> c.PromptExperiment:
    require_role(request, c.UserRole.admin)
    return service.create_prompt_experiment(payload, request)


@router.patch("/api/prompts/experiments/{experiment_id}", response_model=c.PromptExperiment)
def patch_prompt_experiment(
    experiment_id: str, payload: c.PatchPromptExperimentRequest, request: Request
) -> c.PromptExperiment:
    require_role(request, c.UserRole.admin)
    return service.patch_prompt_experiment(experiment_id, payload, request)
