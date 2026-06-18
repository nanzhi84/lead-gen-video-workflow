from __future__ import annotations

from packages.publishing.platform_adapter import PublishOutcome, PublishPayload
from packages.publishing.publish_executor import run_item_publish


class RecordingAdapter:
    adapter_id = "recording.publish"

    def __init__(self, *, fail_account_id: str | None = None) -> None:
        self.fail_account_id = fail_account_id
        self.payloads: list[PublishPayload] = []

    def publish(self, payload: PublishPayload) -> PublishOutcome:
        self.payloads.append(payload)
        success = self.fail_account_id is None or payload.account_id != self.fail_account_id
        return PublishOutcome(
            success=success,
            adapter_id=self.adapter_id,
            external_task_id=f"task-{payload.account_id or 'single'}" if success else None,
            results=[{"platform": payload.platforms[0], "account_id": payload.account_id}],
            error_message=None if success else "adapter failed",
        )


def test_run_item_publish_without_targets_calls_adapter_once() -> None:
    adapter = RecordingAdapter()
    base_payload = PublishPayload(title="Title", platforms=("douyin",))

    outcome, per_account_results = run_item_publish(
        adapter,
        base_payload,
        targets=[],
        resolve_session=lambda _account_id: None,
        resolve_video=lambda: "unused.mp4",
    )

    assert outcome.success is True
    assert outcome.external_task_id == "task-single"
    assert per_account_results == []
    assert adapter.payloads == [base_payload]


def test_run_item_publish_with_targets_publishes_each_account() -> None:
    adapter = RecordingAdapter()
    base_payload = PublishPayload(title="Title", platforms=("douyin",))

    outcome, per_account_results = run_item_publish(
        adapter,
        base_payload,
        targets=[("acct_1", "Account One"), ("acct_2", "Account Two")],
        resolve_session=lambda account_id: f'{{"account":"{account_id}"}}',
        resolve_video=lambda: "/tmp/video.mp4",
    )

    assert outcome.success is True
    assert outcome.results == per_account_results
    assert [payload.account_id for payload in adapter.payloads] == ["acct_1", "acct_2"]
    assert [payload.account_name for payload in adapter.payloads] == ["Account One", "Account Two"]
    assert [payload.storage_state_json for payload in adapter.payloads] == [
        '{"account":"acct_1"}',
        '{"account":"acct_2"}',
    ]
    assert {result["external_task_id"] for result in per_account_results} == {
        "task-acct_1",
        "task-acct_2",
    }


def test_run_item_publish_missing_session_fails_only_that_account() -> None:
    adapter = RecordingAdapter()
    base_payload = PublishPayload(title="Title", platforms=("douyin",))

    outcome, per_account_results = run_item_publish(
        adapter,
        base_payload,
        targets=[("acct_1", "Account One"), ("acct_2", "Account Two")],
        resolve_session=lambda account_id: '{"ok":true}' if account_id == "acct_1" else None,
        resolve_video=lambda: "/tmp/video.mp4",
    )

    assert outcome.success is False
    assert outcome.error_message
    assert [payload.account_id for payload in adapter.payloads] == ["acct_1"]
    assert per_account_results == [
        {
            "account_id": "acct_1",
            "account_name": "Account One",
            "success": True,
            "external_task_id": "task-acct_1",
            "error": None,
        },
        {
            "account_id": "acct_2",
            "account_name": "Account Two",
            "success": False,
            "external_task_id": None,
            "error": "Missing active browser session.",
        },
    ]
