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

def provider_profiles(
    request: Request,
    limit: int = 50,
    provider_id: str | None = None,
    capability: str | None = None,
    environment: str | None = None,
) -> c.PageResponse[c.ProviderProfile]:
    if provider_repository(request) is not None:
        values = provider_repository(request).list_profiles(
            provider_id=provider_id,
            capability=capability,
            environment=environment,
            limit=limit,
        )
        return c.PageResponse(items=values, total_hint=len(values), request_id=request_id())
    values = list(repository(request).provider_profiles.values())
    if provider_id:
        values = [profile for profile in values if profile.provider_id == provider_id]
    if capability:
        values = [profile for profile in values if profile.capability == capability]
    if environment:
        values = [profile for profile in values if profile.environment == environment]
    return page(values, limit)


def create_provider_profile(payload: c.CreateProviderProfileRequest, request: Request) -> c.ProviderProfile:
    if provider_repository(request) is not None:
        return provider_repository(request).create_profile(payload)
    profile = c.ProviderProfile(id=new_id("provider_profile"), **payload.model_dump())
    repository(request).provider_profiles[profile.id] = profile
    return profile


def patch_provider_profile(
    profile_id: str, payload: c.PatchProviderProfileRequest, request: Request
) -> c.ProviderProfile:
    if provider_repository(request) is not None:
        return provider_repository(request).patch_profile(profile_id, payload)
    return repository(request).patch(repository(request).provider_profiles, profile_id, payload.model_dump(exclude_none=True))


def test_provider_profile(
    profile_id: str, payload: c.TestProviderProfileRequest, request: Request
) -> c.ProviderHealthCheckResponse:
    if provider_repository(request) is not None:
        return provider_repository(request).test_profile(profile_id, payload)
    return c.ProviderHealthCheckResponse(profile_id=profile_id, ok=profile_id in repository(request).provider_profiles, latency_ms=1)


def provider_capabilities(request: Request) -> list[c.ProviderCapability]:

    if provider_repository(request) is not None:
        return provider_repository(request).list_capabilities()
    return list(repository(request).provider_capabilities.values())


def price_catalogs(
    request: Request,
    limit: int = 50,
    provider_id: str | None = None,
    active_only: bool = False,
) -> c.PageResponse[c.ProviderPriceCatalog]:
    if provider_repository(request) is not None:
        values = provider_repository(request).list_price_catalogs(
            provider_id=provider_id,
            active_only=active_only,
            limit=limit,
        )
        return c.PageResponse(items=values, total_hint=len(values), request_id=request_id())
    values = list(repository(request).price_catalogs.values())
    if provider_id:
        values = [catalog for catalog in values if catalog.provider_id == provider_id]
    if active_only:
        values = [catalog for catalog in values if catalog.status == "published"]
    return page(values, limit)


def upsert_price_catalog(payload: c.UpsertPriceCatalogRequest, request: Request) -> c.ProviderPriceCatalog:
    if provider_repository(request) is not None:
        return provider_repository(request).upsert_price_catalog(payload)
    repository(request).price_catalogs[payload.catalog.id] = payload.catalog
    for item in payload.items:
        repository(request).price_items[item.id] = item
    return payload.catalog


def approve_price_catalog(
    catalog_id: str, payload: c.GovernedActionRequest, request: Request
) -> c.ProviderPriceCatalog:
    if provider_repository(request) is not None:
        return provider_repository(request).patch_price_catalog_status(catalog_id, "approved", payload)
    return repository(request).patch(repository(request).price_catalogs, catalog_id, {"status": "approved"})


def publish_price_catalog(
    catalog_id: str, payload: c.GovernedActionRequest, request: Request
) -> c.ProviderPriceCatalog:
    if provider_repository(request) is not None:
        return provider_repository(request).patch_price_catalog_status(catalog_id, "published", payload)
    return repository(request).patch(repository(request).price_catalogs, catalog_id, {"status": "published"})


def deprecate_price_catalog(
    catalog_id: str, payload: c.GovernedActionRequest, request: Request
) -> c.ProviderPriceCatalog:
    if provider_repository(request) is not None:
        return provider_repository(request).patch_price_catalog_status(catalog_id, "deprecated", payload)
    return repository(request).patch(repository(request).price_catalogs, catalog_id, {"status": "deprecated"})


def provider_usage(
    request: Request,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    provider_id: str | None = None,
    case_id: str | None = None,
) -> c.ProviderUsageReport:
    if ops_repository(request) is not None:
        return ops_repository(request).provider_usage(
            window_start=window_start,
            window_end=window_end,
            provider_id=provider_id,
            case_id=case_id,
        )
    invocations = list(repository(request).provider_invocations.values())
    if provider_id:
        invocations = [item for item in invocations if item.provider_id == provider_id]
    if case_id:
        invocations = [item for item in invocations if item.case_id == case_id]
    amount = sum((item.estimated_cost.amount for item in invocations if item.estimated_cost), c.Decimal("0"))
    return c.ProviderUsageReport(
        invocations=len(invocations),
        estimated_cost=c.Money(amount=amount, currency="CNY"),
        unpriced_invocation_count=len([item for item in invocations if item.billing_status == "unpriced"]),
    )


def provider_balances(
    request: Request,
    provider_id: str | None = None,
    environment: str | None = None,
) -> c.ProviderBalanceReport:
    if provider_repository(request) is not None:
        return provider_repository(request).balances(
            request_id=request_id(),
            provider_id=provider_id,
            environment=environment,
        )
    providers = sorted({profile.provider_id for profile in repository(request).provider_profiles.values()})
    return c.ProviderBalanceReport(
        items=[
            c.ProviderBalanceItem(
                provider_id=provider_id,
                balance=c.Money(amount=9999, currency="CNY"),
                quota_remaining=1_000_000,
                checked_at=c.utcnow(),
                status="ok",
            )
            for provider_id in providers
        ],
        request_id=request_id(),
    )


def reconcile_billing(payload: c.ReconcileBillingRequest, request: Request) -> c.ReconcileBillingResponse:
    if ops_repository(request) is not None:
        return ops_repository(request).reconcile_billing(payload, request_id())
    return c.ReconcileBillingResponse(reconciliation_run_id=new_id("recon"), status="queued", request_id=request_id())
