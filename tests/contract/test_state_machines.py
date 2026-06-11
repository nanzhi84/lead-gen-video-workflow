import pytest

from packages.core.contracts import (
    CaseMemory,
    ErrorCode,
    JobStatus,
    NodeStatus,
    ProviderStatus,
    RunStatus,
)
from packages.core.contracts.state_machines import assert_transition
from packages.core.workflow import NodeExecutionError


def test_provider_status_matches_spec_terminal_and_non_status_error_codes():
    assert {status.value for status in ProviderStatus} == {
        "prepared",
        "submitted",
        "polling",
        "succeeded",
        "failed",
        "timed_out",
        "cancelled",
    }


def test_core_state_machines_allow_spec_paths_and_reject_failed_to_running():
    assert_transition("job", JobStatus.draft, JobStatus.queued)
    assert_transition("run", RunStatus.running, RunStatus.cancelling)
    assert_transition("node", NodeStatus.pending, NodeStatus.skipped)
    assert_transition("provider", ProviderStatus.submitted, ProviderStatus.polling)

    with pytest.raises(NodeExecutionError) as exc:
        assert_transition("run", RunStatus.failed, RunStatus.running)

    assert exc.value.error.code == ErrorCode.workflow_invalid_transition


def test_prompt_version_draft_cannot_publish_directly():
    assert_transition("prompt_version", "draft", "approved")
    assert_transition("prompt_version", "approved", "published")

    with pytest.raises(NodeExecutionError):
        assert_transition("prompt_version", "draft", "published")


def test_cancelled_upload_cannot_complete():
    assert_transition("upload_session", "prepared", "uploading")
    assert_transition("upload_session", "uploading", "cancelled")

    with pytest.raises(NodeExecutionError):
        assert_transition("upload_session", "cancelled", "completed")


def test_case_memory_requires_approved_before_active():
    assert {item for item in CaseMemory.model_fields["status"].annotation.__args__} >= {
        "proposed",
        "approved",
        "active",
        "deprecated",
        "rejected",
        "superseded",
    }
    assert_transition("case_memory", "proposed", "approved")
    assert_transition("case_memory", "approved", "active")

    with pytest.raises(NodeExecutionError):
        assert_transition("case_memory", "proposed", "active")
