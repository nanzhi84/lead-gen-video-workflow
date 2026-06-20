"""Row → contract mappers for the publishing-center account foundation."""

from __future__ import annotations

from packages.core.contracts import CasePublishTarget, Client, PublishAccount
from packages.core.storage.database import CasePublishTargetRow, ClientRow, PublishAccountRow


def client_row_to_contract(row: ClientRow) -> Client:
    return Client(
        id=row.id,
        name=row.name,
        remark=row.remark,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        schema_version=row.schema_version,
    )


def publish_account_row_to_contract(row: PublishAccountRow) -> PublishAccount:
    return PublishAccount(
        id=row.id,
        client_id=row.client_id,
        platform=row.platform,
        account_name=row.account_name,
        platform_uid=row.platform_uid,
        xiaovmao_uid=row.xiaovmao_uid,
        login_state="unknown",
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        schema_version=row.schema_version,
    )


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
