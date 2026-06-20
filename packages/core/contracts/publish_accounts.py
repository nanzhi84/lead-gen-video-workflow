"""Publishing-account domain contracts (publishing center §13).

These are the **persistent, operator-managed** records that back the publishing
center, distinct from ``PlatformAccount`` (``publishing.py``) — the latter is the
*ephemeral probe result* returned by a publish adapter. Here:

- ``Client`` — a customer/brand we publish on behalf of.
- ``PublishAccount`` — one of a client's platform-account binding anchors. The
  platform login/session lives in 小V猫; ``login_state`` is computed live and never
  persisted.
- ``CasePublishTarget`` — a binding from a Case to one of its client's accounts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from packages.core.contracts.base import ContractModel, EntityMeta

PublishPlatform = Literal["douyin", "shipinhao", "kuaishou", "xiaohongshu"]
# Live login state of a 小V猫-managed platform account, computed at read time from
# 小V猫's ``CatBridge`` ``isLogin`` (NOT persisted — 小V猫 is the session source of truth).
PublishLoginState = Literal["logged_in", "logged_out", "unknown"]
ArchivableStatus = Literal["active", "archived"]


class Client(EntityMeta):
    """A customer/brand whose platform accounts we publish on behalf of."""

    name: str
    remark: str = ""
    status: ArchivableStatus = "active"


class PublishAccount(EntityMeta):
    """A client's persistent publishing account on one platform — a binding anchor
    that maps to a 小V猫-managed account via ``xiaovmao_uid``.

    The platform session lives **inside 小V猫** (never in our DB/SecretStore nor in
    this contract). ``login_state`` is computed live at read time from 小V猫's
    ``CatBridge`` ``isLogin`` and is **not persisted**.
    """

    client_id: str
    platform: PublishPlatform
    account_name: str
    platform_uid: str | None = None
    xiaovmao_uid: str | None = None
    login_state: PublishLoginState = "unknown"
    status: ArchivableStatus = "active"


class CasePublishTarget(EntityMeta):
    """Binding: a Case publishes to one of its client's accounts.

    ``platform`` / ``account_name`` / ``client_id`` are denormalized read-only
    conveniences hydrated from the bound account.
    """

    case_id: str
    account_id: str
    enabled: bool = True
    platform: PublishPlatform | None = None
    account_name: str | None = None
    client_id: str | None = None


# --- request bodies ---


class CreateClientRequest(ContractModel):
    name: str
    remark: str = ""


class PatchClientRequest(ContractModel):
    name: str | None = None
    remark: str | None = None
    status: ArchivableStatus | None = None


class CreatePublishAccountRequest(ContractModel):
    client_id: str
    platform: PublishPlatform
    account_name: str
    platform_uid: str | None = None
    xiaovmao_uid: str | None = None


class PatchPublishAccountRequest(ContractModel):
    account_name: str | None = None
    platform_uid: str | None = None
    xiaovmao_uid: str | None = None
    status: ArchivableStatus | None = None


class SetCasePublishTargetsRequest(ContractModel):
    """Replace the full set of accounts a Case publishes to (idempotent PUT)."""

    account_ids: list[str] = Field(default_factory=list)


# --- QR login (CDP-driven 小V猫) + session validation responses ---


class BeginLoginResponse(ContractModel):
    """A started QR-login flow against 小V猫. The QR is **streamed in real time** over
    the WebSocket at ``stream_path`` — 小V猫's platform QR refreshes fast, so the socket
    pushes each fresh frame instead of returning one snapshot. ``Cache-Control: no-store``."""

    login_id: str
    account_id: str
    platform: PublishPlatform
    status: str  # pending
    stream_path: str  # WS path to subscribe: /api/publish/accounts/login/{login_id}/stream
    request_id: str


class LoginStatusResponse(ContractModel):
    """Fallback poll of a login flow (the WebSocket stream is the primary channel)."""

    login_id: str
    account_id: str
    status: str  # pending | verifying | active | failed
    detail: str | None = None
    login_state: PublishLoginState
    request_id: str


class ValidateSessionResponse(ContractModel):
    account_id: str
    login_state: PublishLoginState
    last_checked_at: datetime | None = None
    request_id: str


class LoginStreamEvent(ContractModel):
    """One event pushed over the login WebSocket stream (``stream_path``)."""

    type: Literal["qr", "status", "account", "error"]
    qr_image: str | None = None  # type=qr — data-url credential; never persist/log
    status: str | None = None  # type=status — pending|verifying|active|failed
    detail: str | None = None
    account: PublishAccount | None = None  # type=account — the newly-added account
