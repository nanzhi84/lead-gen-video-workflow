"""QR-login + session-validation orchestration (publishing center, PR3).

Drives the browser session driver (sandbox default; Playwright/UNVERIFIED on the Mac
Mini) to start a QR login, poll for the scan, and persist the resulting storage_state
via PR2's ``store_account_session`` (encrypted in the SecretStore). Also validates a
stored session against the live creator backend.

Pending-login state lives in an in-memory, single-host registry on ``app.state``; the
storage_state payload is NEVER returned by the API (only ``has_session`` /
``session_status`` / the QR). The driver session is closed on every terminal poll and
on TTL sweep so no browser is leaked.
"""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from apps.api.common import (
    accounts_repository,
    publish_browser_driver,
    publish_login_registry,
    repository,
    request_id,
    secret_store,
)
from apps.api.dependencies import not_found_response
from packages.core import contracts as c
from packages.core.contracts.base import utcnow
from packages.publishing import MemoryAccountsRepository
from packages.publishing.account_sessions import store_account_session

logger = logging.getLogger(__name__)


def _repo(request: Request):
    return accounts_repository(request) or MemoryAccountsRepository(repository(request))


def _sweep(request: Request) -> None:
    driver = publish_browser_driver(request)
    for login_id in publish_login_registry(request).sweep_expired():
        driver.close(login_id)


def begin_login(account_id: str, request: Request) -> c.BeginLoginResponse | JSONResponse:
    repo = _repo(request)
    account = repo.get_account(account_id)
    if account is None:
        return not_found_response("Publish account not found")
    _sweep(request)
    handle = publish_browser_driver(request).begin_login(account.platform)
    publish_login_registry(request).add(
        login_id=handle.login_token, account_id=account_id, platform=account.platform
    )
    return c.BeginLoginResponse(
        login_id=handle.login_token,
        account_id=account_id,
        platform=account.platform,
        status="pending",
        qr_image=handle.qr_image,
        request_id=request_id(),
    )


def poll_login(
    account_id: str, login_id: str, request: Request
) -> c.LoginStatusResponse | JSONResponse:
    _sweep(request)  # reap TTL-expired logins (incl. this one) on every poll
    registry = publish_login_registry(request)
    session = registry.get(login_id)
    if session is None or session.account_id != account_id:
        return not_found_response("Login session not found")
    repo = _repo(request)
    driver = publish_browser_driver(request)
    if session.status == "pending":
        result = driver.poll_login(login_id)
        if result.status == "success" and result.storage_state_json:
            store_account_session(repo, secret_store(request), account_id, result.storage_state_json)
            driver.close(login_id)  # session captured — release the browser
            registry.update(login_id, status="active")
        elif result.status == "pending":
            pass  # still waiting for the operator to scan
        else:
            # failed, or a "success" with no storage_state — release the browser, mark failed
            driver.close(login_id)
            registry.update(login_id, status="failed", detail=result.detail or "login did not complete")
        session = registry.get(login_id) or session
    account = repo.get_account(account_id)
    return c.LoginStatusResponse(
        login_id=login_id,
        account_id=account_id,
        status=session.status,
        detail=session.detail,
        session_status=account.session_status if account is not None else "never_logged_in",
        request_id=request_id(),
    )


def validate_session(account_id: str, request: Request) -> c.ValidateSessionResponse | JSONResponse:
    repo = _repo(request)
    account = repo.get_account(account_id)
    if account is None:
        return not_found_response("Publish account not found")
    # Resolve the session payload via the ref (never read it off the contract).
    ref = repo.get_account_session_ref(account_id)
    if ref is None:
        return c.ValidateSessionResponse(
            account_id=account_id,
            session_status=account.session_status,
            has_session=False,
            last_validated_at=account.last_validated_at,
            request_id=request_id(),
        )
    storage_state = secret_store(request).get(ref)
    if storage_state is None:
        # The session secret vanished out-of-band — treat as no session.
        updated, _old = repo.set_account_session(
            account_id, secret_ref=None, session_status="expired", last_validated_at=utcnow()
        )
    else:
        active = publish_browser_driver(request).validate_session(account.platform, storage_state).active
        updated, _old = repo.set_account_session(
            account_id,
            secret_ref=ref,
            session_status="active" if active else "expired",
            session_expires_at=account.session_expires_at,
            last_validated_at=utcnow(),
        )
    target = updated or account
    return c.ValidateSessionResponse(
        account_id=account_id,
        session_status=target.session_status,
        has_session=target.has_session,
        last_validated_at=target.last_validated_at,
        request_id=request_id(),
    )
