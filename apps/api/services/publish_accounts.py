"""Publishing-center account foundation service (clients / accounts / case targets).

Dual-track: uses the SqlAlchemy accounts repo when configured, else an in-memory
mirror over the runtime Repository (memory backend / tests). Account browser
sessions (Playwright ``storage_state``) are stored in the SecretStore via
``packages.publishing.account_sessions``; this layer never persists the payload.
"""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from apps.api.common import accounts_repository, get_case, repository, request_id, secret_store
from apps.api.dependencies import not_found_response
from packages.core import contracts as c
from packages.core.workflow import NodeExecutionError
from packages.publishing import MemoryAccountsRepository
from packages.publishing.account_sessions import store_account_session

logger = logging.getLogger(__name__)


def _repo(request: Request):
    return accounts_repository(request) or MemoryAccountsRepository(repository(request))


# --- clients ---


def list_clients(
    request: Request, *, limit: int = 50, include_archived: bool = False
) -> c.PageResponse[c.Client]:
    items = _repo(request).list_clients(include_archived=include_archived, limit=limit)
    return c.PageResponse(items=items, total_hint=len(items), request_id=request_id())


def create_client(payload: c.CreateClientRequest, request: Request) -> c.Client:
    return _repo(request).create_client(name=payload.name, remark=payload.remark)


def patch_client(
    client_id: str, payload: c.PatchClientRequest, request: Request
) -> c.Client | JSONResponse:
    updated = _repo(request).patch_client(
        client_id, name=payload.name, remark=payload.remark, status=payload.status
    )
    if updated is None:
        return not_found_response("Client not found")
    return updated


def delete_client(client_id: str, request: Request) -> c.OkResponse | JSONResponse:
    repo = _repo(request)
    if repo.get_client(client_id) is None:
        return not_found_response("Client not found")
    repo.patch_client(client_id, status="archived")
    return c.OkResponse(request_id=request_id())


# --- accounts ---


def list_accounts(
    request: Request,
    *,
    client_id: str | None = None,
    platform: str | None = None,
    limit: int = 50,
    include_archived: bool = False,
) -> c.PageResponse[c.PublishAccount]:
    items = _repo(request).list_accounts(
        client_id=client_id, platform=platform, include_archived=include_archived, limit=limit
    )
    return c.PageResponse(items=items, total_hint=len(items), request_id=request_id())


def create_account(payload: c.CreatePublishAccountRequest, request: Request) -> c.PublishAccount:
    repo = _repo(request)
    if not repo.client_exists(payload.client_id):
        raise NodeExecutionError(
            c.ErrorCode.validation_invalid_options, f"Client {payload.client_id} does not exist."
        )
    existing = repo.find_account_by_natural_key(
        client_id=payload.client_id, platform=payload.platform, account_name=payload.account_name
    )
    if existing is not None:
        raise NodeExecutionError(
            c.ErrorCode.validation_conflict,
            f"Account '{payload.account_name}' already exists for this client on {payload.platform}.",
        )
    return repo.create_account(
        client_id=payload.client_id,
        platform=payload.platform,
        account_name=payload.account_name,
        platform_uid=payload.platform_uid,
    )


def patch_account(
    account_id: str, payload: c.PatchPublishAccountRequest, request: Request
) -> c.PublishAccount | JSONResponse:
    repo = _repo(request)
    current = repo.get_account(account_id)
    if current is None:
        return not_found_response("Publish account not found")
    # A rename must not collide with another account of the same client+platform.
    if payload.account_name is not None and payload.account_name != current.account_name:
        clash = repo.find_account_by_natural_key(
            client_id=current.client_id, platform=current.platform, account_name=payload.account_name
        )
        if clash is not None and clash.id != account_id:
            raise NodeExecutionError(
                c.ErrorCode.validation_conflict,
                f"Account '{payload.account_name}' already exists for this client on {current.platform}.",
            )
    if payload.status == "archived":
        _clear_account_publish_state(repo, request, account_id)
    updated = repo.patch_account(
        account_id,
        account_name=payload.account_name,
        platform_uid=payload.platform_uid,
        platform_uid_set="platform_uid" in payload.model_fields_set,
        status=payload.status,
    )
    if updated is None:
        return not_found_response("Publish account not found")
    return updated


def delete_account(account_id: str, request: Request) -> c.OkResponse | JSONResponse:
    repo = _repo(request)
    if repo.get_account(account_id) is None:
        return not_found_response("Publish account not found")
    _clear_account_publish_state(repo, request, account_id)
    repo.patch_account(account_id, status="archived")
    return c.OkResponse(request_id=request_id())


def _clear_account_publish_state(repo, request: Request, account_id: str) -> None:
    from apps.api.services import publish_login

    publish_login.cancel_logins_for_account(account_id, request)
    # Archive under the repository's row-level guard so concurrent session writes
    # cannot leave an archived account with an active browser session.
    _archived, old_ref = repo.archive_account(account_id)
    publish_login.cancel_logins_for_account(account_id, request)
    if old_ref is not None:
        secret_store(request).disable(old_ref)
        _audit(request, account_id, "publish.account.session_cleared")
    # Don't leave case targets bound to an archived account.
    repo.delete_targets_for_account(account_id)


def set_account_session(
    account_id: str, storage_state_json: str, request: Request, *, session_expires_at=None
) -> c.PublishAccount | None:
    """Store (or replace) an account's encrypted browser session.

    Called by the PR3 QR-login flow once a scan succeeds. Any prior session secret
    is disabled by ``store_account_session`` so a replace leaves no orphan.
    """
    updated = store_account_session(
        _repo(request),
        secret_store(request),
        account_id,
        storage_state_json,
        session_expires_at=session_expires_at,
    )
    if updated is not None:
        _audit(request, account_id, "publish.account.session_set")
    return updated


def _audit(request: Request, account_id: str, topic: str) -> None:
    logger.info("%s account_id=%s", topic, account_id)
    try:
        repository(request).create_event(
            topic, "publish_account", account_id, {"account_id": account_id}, event_type="account_audit"
        )
    except Exception:  # pragma: no cover - audit is best-effort, never blocks the op
        logger.debug("audit event emit failed for %s", topic, exc_info=True)


# --- case targets ---


def list_case_targets(case_id: str, request: Request) -> c.PageResponse[c.CasePublishTarget]:
    items = _repo(request).list_targets(case_id)
    return c.PageResponse(items=items, total_hint=len(items), request_id=request_id())


def set_case_targets(
    case_id: str, payload: c.SetCasePublishTargetsRequest, request: Request
) -> c.PageResponse[c.CasePublishTarget]:
    get_case(request, case_id)  # raises validation_missing_case if the case doesn't exist
    repo = _repo(request)
    account_ids = list(dict.fromkeys(payload.account_ids))
    client_map = repo.accounts_client_map(account_ids)
    missing = [account_id for account_id in account_ids if account_id not in client_map]
    if missing:
        raise NodeExecutionError(
            c.ErrorCode.validation_invalid_options, f"Unknown publish account(s): {', '.join(missing)}."
        )
    if len(set(client_map.values())) > 1:
        raise NodeExecutionError(
            c.ErrorCode.validation_invalid_options,
            "All publish targets for a case must belong to the same client.",
        )
    items = repo.set_targets(case_id, account_ids)
    return c.PageResponse(items=items, total_hint=len(items), request_id=request_id())
