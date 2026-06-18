from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace

from packages.publishing.platform_adapter import (
    PublishOutcome,
    PublishPayload,
    PublishPlatformAdapter,
)

PublishTarget = tuple[str, str | None]


def run_item_publish(
    adapter: PublishPlatformAdapter,
    base_payload: PublishPayload,
    *,
    targets: Iterable[PublishTarget],
    resolve_session: Callable[[str], str | None],
    resolve_video: Callable[[], str | None],
) -> tuple[PublishOutcome, list[dict]]:
    target_list = list(targets)
    if not target_list:
        return adapter.publish(base_payload), []

    per_account_results: list[dict] = []
    external_task_ids: list[str] = []
    all_succeeded = True
    for account_id, account_name in target_list:
        storage_state_json = resolve_session(account_id)
        if storage_state_json is None:
            all_succeeded = False
            per_account_results.append(
                _account_result(
                    account_id=account_id,
                    account_name=account_name,
                    success=False,
                    external_task_id=None,
                    error="Missing active browser session.",
                )
            )
            continue

        outcome = adapter.publish(
            replace(
                base_payload,
                account_id=account_id,
                account_name=account_name,
                storage_state_json=storage_state_json,
                video_path=resolve_video(),
            )
        )
        if outcome.external_task_id:
            external_task_ids.append(outcome.external_task_id)
        if not outcome.success:
            all_succeeded = False
        per_account_results.append(
            _account_result(
                account_id=account_id,
                account_name=account_name,
                success=outcome.success,
                external_task_id=outcome.external_task_id,
                error=outcome.error_message,
            )
        )

    external_task_id = external_task_ids[0] if all_succeeded and len(external_task_ids) == 1 else None
    return (
        PublishOutcome(
            success=all_succeeded,
            adapter_id=adapter.adapter_id,
            external_task_id=external_task_id,
            results=per_account_results,
            error_message=None if all_succeeded else "One or more account publishes failed.",
        ),
        per_account_results,
    )


def _account_result(
    *,
    account_id: str,
    account_name: str | None,
    success: bool,
    external_task_id: str | None,
    error: str | None,
) -> dict:
    return {
        "account_id": account_id,
        "account_name": account_name,
        "success": success,
        "external_task_id": external_task_id,
        "error": error,
    }
