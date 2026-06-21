"""Row → contract mappers for the publishing-center account foundation."""

from __future__ import annotations

from packages.core.contracts import CasePublishTarget, Client, PublishAccount
from packages.core.storage.database import CasePublishTargetRow, ClientRow, PublishAccountRow
from packages.core.storage.row_mapper import map_row


def client_row_to_contract(row: ClientRow) -> Client:
    return map_row(row, Client)


def publish_account_row_to_contract(row: PublishAccountRow) -> PublishAccount:
    # login_state is not persisted on the row — it is a live signal resolved
    # elsewhere; the mapper reports "unknown" until that lookup runs.
    return map_row(row, PublishAccount, login_state="unknown")


def case_publish_target_row_to_contract(
    row: CasePublishTargetRow, account: PublishAccountRow | None = None
) -> CasePublishTarget:
    return CasePublishTarget(
        id=row.id,
        case_id=row.case_id,
        account_id=row.account_id,
        enabled=row.enabled,
        platform=account.platform if account is not None else None,
        account_name=account.account_name if account is not None else None,
        client_id=account.client_id if account is not None else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
        schema_version=row.schema_version,
    )
