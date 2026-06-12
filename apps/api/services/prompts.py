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
from packages.core.storage.prompt_groups import prompt_variable_hints
from packages.core.observability import metric_snapshot
from packages.core.registration_codes import hash_registration_code
from packages.core.storage.object_store import parse_local_uri
from packages.core.storage.repository import new_id
from packages.core.workflow import NodeExecutionError

def list_prompts(
    request: Request,
    limit: int = 50,
    status: str | None = None,
    purpose: str | None = None,
) -> c.PageResponse[c.PromptTemplateView]:
    if prompt_repository(request) is not None:
        values = prompt_repository(request).list_templates(status=status, purpose=purpose, limit=limit)
        return c.PageResponse(items=values, total_hint=len(values), request_id=request_id())
    views = []
    for template in repository(request).prompt_templates.values():
        if status and template.status != status:
            continue
        if purpose and template.purpose != purpose:
            continue
        published = next(
            (
                version
                for version in repository(request).prompt_versions.values()
                if version.prompt_template_id == template.id and version.status == "published"
            ),
            None,
        )
        views.append(
            c.PromptTemplateView(
                template=template,
                published_version=published,
                variable_hints=prompt_variable_hints(template.id),
            )
        )
    return page(views, limit)


def create_prompt(payload: c.CreatePromptTemplateRequest, request: Request) -> c.PromptTemplateView:
    if prompt_repository(request) is not None:
        return prompt_repository(request).create_template(payload)
    template = c.PromptTemplate(id=new_id("prompt"), status="draft", **payload.model_dump())
    repository(request).prompt_templates[template.id] = template
    return c.PromptTemplateView(template=template, variable_hints=prompt_variable_hints(template.id))


def prompt_versions(request: Request, template_id: str, limit: int = 50) -> c.PageResponse[c.PromptVersionView]:

    if prompt_repository(request) is not None:
        values = prompt_repository(request).list_versions(template_id, limit=limit)
        return c.PageResponse(items=values, total_hint=len(values), request_id=request_id())
    template = repository(request).prompt_templates[template_id]
    versions = [
        c.PromptVersionView(version=version, template=template)
        for version in repository(request).prompt_versions.values()
        if version.prompt_template_id == template_id
    ]
    return page(versions, limit)


def create_prompt_version(
    template_id: str, payload: c.CreatePromptVersionRequest, request: Request
) -> c.PromptVersionView:
    if prompt_repository(request) is not None:
        return prompt_repository(request).create_version(template_id, payload)
    version = c.PromptVersion(
        id=new_id("pver"),
        prompt_template_id=template_id,
        content=payload.content,
        changelog=payload.changelog,
    )
    repository(request).prompt_versions[version.id] = version
    return c.PromptVersionView(version=version, template=repository(request).prompt_templates[template_id])


def approve_prompt_version(
    template_id: str, version_id: str, payload: c.ApprovePromptVersionRequest, request: Request
) -> c.PromptVersionView:
    if prompt_repository(request) is not None:
        return prompt_repository(request).approve_version(template_id, version_id, payload)
    version = repository(request).prompt_versions[version_id]
    if version.status == "draft":
        assert_transition("prompt_version", version.status, "reviewing")
        version = repository(request).patch(repository(request).prompt_versions, version_id, {"status": "reviewing"})
    assert_transition("prompt_version", version.status, "approved")
    version = repository(request).patch(repository(request).prompt_versions, version_id, {"status": "approved", "approved_at": c.utcnow()})
    return c.PromptVersionView(version=version, template=repository(request).prompt_templates[template_id])


def publish_prompt_version(
    template_id: str, version_id: str, payload: c.PublishPromptVersionRequest, request: Request
) -> c.PromptVersionView:
    if prompt_repository(request) is not None:
        return prompt_repository(request).publish_version(template_id, version_id, payload)
    version = repository(request).prompt_versions[version_id]
    assert_transition("prompt_version", version.status, "published")
    version = repository(request).patch(repository(request).prompt_versions, version_id, {"status": "published", "published_at": c.utcnow()})
    return c.PromptVersionView(version=version, template=repository(request).prompt_templates[template_id])


def rollback_prompt(
    template_id: str, payload: c.RollbackPromptRequest, request: Request
) -> c.PromptVersionView:
    if prompt_repository(request) is not None:
        return prompt_repository(request).rollback(template_id, payload)
    version = repository(request).prompt_versions[payload.target_version_id]
    assert_transition("prompt_version", version.status, "published")
    version = repository(request).patch(repository(request).prompt_versions, payload.target_version_id, {"status": "published"})
    return c.PromptVersionView(version=version, template=repository(request).prompt_templates[template_id])


def prompt_bindings(request: Request, limit: int = 50) -> c.PageResponse[c.PromptBindingView]:

    if prompt_repository(request) is not None:
        values = prompt_repository(request).list_bindings(limit=limit)
        return c.PageResponse(items=values, total_hint=len(values), request_id=request_id())
    return page(
        [
            c.PromptBindingView(
                binding=binding,
                resolved_version=repository(request).prompt_versions.get(binding.prompt_version_id),
            )
            for binding in repository(request).prompt_bindings.values()
        ],
        limit,
    )


def create_prompt_binding(payload: c.CreatePromptBindingRequest, request: Request) -> c.PromptBindingView:
    if prompt_repository(request) is not None:
        return prompt_repository(request).create_binding(payload)
    binding = c.PromptBinding(id=new_id("pbind"), **payload.model_dump())
    repository(request).prompt_bindings[binding.id] = binding
    return c.PromptBindingView(binding=binding, resolved_version=repository(request).prompt_versions.get(binding.prompt_version_id))


def patch_prompt_binding(
    binding_id: str, payload: c.PatchPromptBindingRequest, request: Request
) -> c.PromptBindingView:
    if prompt_repository(request) is not None:
        return prompt_repository(request).patch_binding(binding_id, payload)
    binding = repository(request).patch(repository(request).prompt_bindings, binding_id, payload.model_dump(exclude_none=True))
    return c.PromptBindingView(binding=binding, resolved_version=repository(request).prompt_versions.get(binding.prompt_version_id))


def prompt_experiments(
    request: Request,
    limit: int = 50,
    prompt_template_id: str | None = None,
    status: str | None = None,
) -> c.PageResponse[c.PromptExperiment]:
    if prompt_repository(request) is not None:
        values = prompt_repository(request).list_experiments(
            prompt_template_id=prompt_template_id,
            status=status,
            limit=limit,
        )
        return c.PageResponse(items=values, total_hint=len(values), request_id=request_id())
    return page(repository(request).prompt_experiments.values(), limit)


def create_prompt_experiment(
    payload: c.CreatePromptExperimentRequest, request: Request
) -> c.PromptExperiment:
    if prompt_repository(request) is not None:
        return prompt_repository(request).create_experiment(payload)
    experiment = c.PromptExperiment(id=new_id("pexp"), **payload.model_dump())
    repository(request).prompt_experiments[experiment.id] = experiment
    return experiment


def patch_prompt_experiment(
    experiment_id: str, payload: c.PatchPromptExperimentRequest, request: Request
) -> c.PromptExperiment:
    if prompt_repository(request) is not None:
        return prompt_repository(request).patch_experiment(experiment_id, payload)
    return repository(request).patch(repository(request).prompt_experiments, experiment_id, payload.model_dump(exclude_none=True))
