"""Publishing-account domain contracts (publishing center §13).

These are the **persistent, operator-managed** records that back the publishing
center, distinct from ``PlatformAccount`` (``publishing.py``) — the latter is the
*ephemeral probe result* returned by a publish adapter. Here:

- ``Client`` — a customer/brand we publish on behalf of.
- ``PublishAccount`` — one of a client's platform accounts. Its browser session
  (Playwright ``storage_state`` / cookies) is a secret stored out-of-band in the
  ``SecretStore``; only ``session_status`` / ``has_session`` are exposed here —
  never the secret ref or the session payload.
- ``CasePublishTarget`` — a binding from a Case to one of its client's accounts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from packages.core.contracts.base import ContractModel, EntityMeta

PublishPlatform = Literal["douyin", "shipinhao", "kuaishou", "xiaohongshu"]
PublishSessionStatus = Literal["never_logged_in", "active", "expired"]
ArchivableStatus = Literal["active", "archived"]


class Client(EntityMeta):
    """A customer/brand whose platform accounts we publish on behalf of."""

    name: str
    remark: str = ""
    status: ArchivableStatus = "active"


class PublishAccount(EntityMeta):
    """A client's persistent publishing account on one platform.

    The browser session lives in the ``SecretStore`` (never in the DB row nor in
    this contract); ``has_session`` + ``session_status`` are the only session
    surface exposed to the API.
    """

    client_id: str
    platform: PublishPlatform
    account_name: str
    platform_uid: str | None = None
    session_status: PublishSessionStatus = "never_logged_in"
    has_session: bool = False
    session_expires_at: datetime | None = None
    last_validated_at: datetime | None = None
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


class PatchPublishAccountRequest(ContractModel):
    account_name: str | None = None
    platform_uid: str | None = None
    status: ArchivableStatus | None = None


class SetCasePublishTargetsRequest(ContractModel):
    """Replace the full set of accounts a Case publishes to (idempotent PUT)."""

    account_ids: list[str] = Field(default_factory=list)


# --- QR login / session validation responses (PR3) ---


class BeginLoginResponse(ContractModel):
    """A started QR-login flow. ``qr_image`` is a login credential (data-url); the API
    marks the response ``Cache-Control: no-store`` — never persist or log it."""

    login_id: str
    account_id: str
    platform: PublishPlatform
    status: str  # pending
    qr_image: str
    request_id: str


class LoginStatusResponse(ContractModel):
    login_id: str
    account_id: str
    status: str  # pending | active | failed
    detail: str | None = None
    session_status: PublishSessionStatus
    request_id: str


class ValidateSessionResponse(ContractModel):
    account_id: str
    session_status: PublishSessionStatus
    has_session: bool
    last_validated_at: datetime | None = None
    request_id: str
