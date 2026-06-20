from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from apps.api.dependencies import SESSION_COOKIE, require_role
from apps.api.services import publish_accounts as service
from apps.api.services import publish_login as login_service
from packages.core import contracts as c

router = APIRouter()


# --- clients ---


@router.get("/api/publish/clients", response_model=c.PageResponse[c.Client])
def list_clients(
    request: Request, limit: int = 50, include_archived: bool = False
) -> c.PageResponse[c.Client]:
    require_role(request, c.UserRole.operator)
    return service.list_clients(request, limit=limit, include_archived=include_archived)


@router.post("/api/publish/clients", response_model=c.Client, status_code=201)
def create_client(payload: c.CreateClientRequest, request: Request) -> c.Client:
    require_role(request, c.UserRole.operator)
    return service.create_client(payload, request)


@router.patch("/api/publish/clients/{client_id}", response_model=c.Client)
def patch_client(
    client_id: str, payload: c.PatchClientRequest, request: Request
) -> c.Client | JSONResponse:
    require_role(request, c.UserRole.operator)
    return service.patch_client(client_id, payload, request)


@router.delete("/api/publish/clients/{client_id}", response_model=c.OkResponse)
def delete_client(client_id: str, request: Request) -> c.OkResponse | JSONResponse:
    require_role(request, c.UserRole.operator)
    return service.delete_client(client_id, request)


# --- accounts ---


@router.get("/api/publish/accounts", response_model=c.PageResponse[c.PublishAccount])
def list_accounts(
    request: Request,
    client_id: str | None = None,
    platform: str | None = None,
    limit: int = 50,
    include_archived: bool = False,
) -> c.PageResponse[c.PublishAccount]:
    require_role(request, c.UserRole.operator)
    return service.list_accounts(
        request, client_id=client_id, platform=platform, limit=limit, include_archived=include_archived
    )


@router.post("/api/publish/accounts", response_model=c.PublishAccount, status_code=201)
def create_account(payload: c.CreatePublishAccountRequest, request: Request) -> c.PublishAccount:
    require_role(request, c.UserRole.operator)
    return service.create_account(payload, request)


@router.patch("/api/publish/accounts/{account_id}", response_model=c.PublishAccount)
def patch_account(
    account_id: str, payload: c.PatchPublishAccountRequest, request: Request
) -> c.PublishAccount | JSONResponse:
    require_role(request, c.UserRole.operator)
    return service.patch_account(account_id, payload, request)


@router.delete("/api/publish/accounts/{account_id}", response_model=c.OkResponse)
def delete_account(account_id: str, request: Request) -> c.OkResponse | JSONResponse:
    require_role(request, c.UserRole.operator)
    return service.delete_account(account_id, request)


# --- case → account targets ---


@router.get(
    "/api/cases/{case_id}/publish-targets", response_model=c.PageResponse[c.CasePublishTarget]
)
def list_case_targets(case_id: str, request: Request) -> c.PageResponse[c.CasePublishTarget]:
    require_role(request, c.UserRole.operator)
    return service.list_case_targets(case_id, request)


@router.put(
    "/api/cases/{case_id}/publish-targets", response_model=c.PageResponse[c.CasePublishTarget]
)
def set_case_targets(
    case_id: str, payload: c.SetCasePublishTargetsRequest, request: Request
) -> c.PageResponse[c.CasePublishTarget]:
    require_role(request, c.UserRole.operator)
    return service.set_case_targets(case_id, payload, request)


# --- QR login + session validation (PR3) ---


@router.post(
    "/api/publish/accounts/{account_id}/login",
    response_model=c.BeginLoginResponse,
    status_code=201,
)
def begin_account_login(
    account_id: str, request: Request, response: Response
) -> c.BeginLoginResponse | JSONResponse:
    require_role(request, c.UserRole.operator)
    response.headers["Cache-Control"] = "no-store"  # the QR is a login credential
    return login_service.begin_login(account_id, request)


@router.websocket("/api/publish/accounts/login/{login_id}/stream")
async def stream_account_login(login_id: str, websocket: WebSocket) -> None:
    if not _authorize_websocket(websocket):
        await websocket.close(code=1008)
        return
    manager = websocket.scope["app"].state.xiaovmao_login_manager
    if manager.poll(login_id) is None:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        while True:
            event = await asyncio.to_thread(manager.next_event, login_id, 15)
            if event is not None:
                await websocket.send_json(event.model_dump(mode="json"))
            session = manager.poll(login_id)
            if session is None:
                break
            if event is None and session.status in {"active", "failed"}:
                break
    except WebSocketDisconnect:
        pass
    finally:
        # Stream closed (terminal, disconnect, or error) → stop the CDP login thread
        # and drop the session so a dropped socket never leaves a login running.
        manager.cancel(login_id)


def _authorize_websocket(websocket: WebSocket) -> bool:
    app = websocket.scope["app"]
    try:
        user = app.state.auth_service.authenticate_token(websocket.cookies.get(SESSION_COOKIE))
        app.state.auth_service.require_role(user, c.UserRole.operator)
    except Exception:
        return False
    return True


@router.get(
    "/api/publish/accounts/{account_id}/login/{login_id}", response_model=c.LoginStatusResponse
)
def poll_account_login(
    account_id: str, login_id: str, request: Request, response: Response
) -> c.LoginStatusResponse | JSONResponse:
    require_role(request, c.UserRole.operator)
    response.headers["Cache-Control"] = "no-store"
    return login_service.poll_login(account_id, login_id, request)


@router.delete(
    "/api/publish/accounts/{account_id}/login/{login_id}", response_model=c.OkResponse
)
def cancel_account_login(
    account_id: str, login_id: str, request: Request
) -> c.OkResponse | JSONResponse:
    require_role(request, c.UserRole.operator)
    return login_service.cancel_login(account_id, login_id, request)


@router.post(
    "/api/publish/accounts/{account_id}/session:validate",
    response_model=c.ValidateSessionResponse,
)
def validate_account_session(
    account_id: str, request: Request
) -> c.ValidateSessionResponse | JSONResponse:
    require_role(request, c.UserRole.operator)
    return login_service.validate_session(account_id, request)
