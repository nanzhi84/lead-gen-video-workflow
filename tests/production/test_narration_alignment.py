from __future__ import annotations

import pytest

from packages.ai.gateway import ProviderResult
from packages.core.contracts import (
    Artifact,
    ArtifactKind,
    DigitalHumanVideoRequest,
    ErrorCode,
    MediaInfo,
    NodeRun,
    NodeStatus,
    ProviderError,
    ProviderInvocation,
    ProviderOptionsSchemaRef,
    ProviderProfile,
    ProviderStatus,
    RunStatus,
    WarningCode,
    WorkflowRun,
)
from packages.core.storage.repository import Repository
from packages.core.workflow import NodeExecutionError
from packages.production.pipeline.digital_human import LocalRuntimeAdapter, RunState


class FailingAsrGateway:
    plugins = {"fake.asr": object()}

    def __init__(self) -> None:
        self.invocation_id = "pinv_failed_asr"

    def invoke(self, call):
        invocation = ProviderInvocation(
            id=self.invocation_id,
            case_id=call.case_id,
            run_id=call.run_id,
            node_run_id=call.node_run_id,
            provider_id="fake.asr",
            model_id="fake-asr",
            provider_profile_id=call.provider_profile_id,
            capability_id=call.capability_id,
            status=ProviderStatus.failed,
            error=ProviderError(
                code=ErrorCode.provider_remote_failed,
                message="ASR provider failed.",
                retryable=True,
            ),
        )
        return invocation, None


def _workflow_with_failing_asr() -> LocalRuntimeAdapter:
    repository = Repository()
    repository.provider_profiles["fake.asr.profile"] = ProviderProfile(
        id="fake.asr.profile",
        provider_id="fake.asr",
        model_id="fake-asr",
        capability="asr.transcribe",
        display_name="Fake ASR",
        environment="local",
        options_schema_ref=ProviderOptionsSchemaRef(schema_id="provider.asr.options"),
    )
    workflow = object.__new__(LocalRuntimeAdapter)
    workflow.repository = repository
    workflow.provider_gateway = FailingAsrGateway()
    return workflow


def _run_state(*, strict_timestamps: bool) -> RunState:
    request = DigitalHumanVideoRequest(
        case_id="case_demo",
        script="第一句介绍痛点。第二句说明方案。第三句引导行动。",
        voice={"voice_id": "voice_sandbox"},
        strictness={"strict_timestamps": strict_timestamps},
    )
    tts = Artifact(
        id="art_tts",
        case_id="case_demo",
        run_id="run_1",
        node_run_id="nr_tts",
        kind=ArtifactKind.audio_tts,
        uri="https://media.example/tts.mp3",
        media_info=MediaInfo(
            media_type="audio",
            codec="mp3",
            format="mp3",
            duration_sec=6.0,
        ),
        payload_schema="uri-only",
    )
    return RunState(request=request, artifacts={ArtifactKind.audio_tts: tts})


def _run() -> WorkflowRun:
    return WorkflowRun(
        id="run_1",
        job_id="job_1",
        case_id="case_demo",
        workflow_template_id="digital_human_v2",
        workflow_version="v1",
        status=RunStatus.running,
    )


def _node_run() -> NodeRun:
    return NodeRun(
        id="nr_alignment",
        run_id="run_1",
        node_id="NarrationAlignment",
        node_version="v1",
        status=NodeStatus.running,
        input_manifest_hash="sha256:test",
    )


def test_narration_alignment_non_strict_estimates_when_asr_fails():
    workflow = _workflow_with_failing_asr()

    output = workflow._narration_alignment(_run(), _node_run(), _run_state(strict_timestamps=False))

    artifacts_by_kind = {artifact.kind: artifact for artifact in output.artifacts}
    narration = artifacts_by_kind[ArtifactKind.narration_units].payload
    alignment = artifacts_by_kind[ArtifactKind.audio_alignment].payload
    assert output.status == NodeStatus.succeeded
    assert output.provider_invocation_ids == ["pinv_failed_asr"]
    assert output.warnings == [WarningCode.timestamp_estimated]
    assert output.degradations
    assert output.degradations[0].details["reason"] == "asr_unavailable_estimated_fallback"
    assert output.degradations[0].details["provider_invocation_id"] == "pinv_failed_asr"
    assert narration["source"] == "estimated"
    assert narration["strict"] is False
    assert narration["warnings"] == [WarningCode.timestamp_estimated.value]
    assert len(narration["units"]) == 3
    assert len(alignment["segments"]) == 3


def test_narration_alignment_strict_raises_when_asr_fails():
    workflow = _workflow_with_failing_asr()

    with pytest.raises(NodeExecutionError) as exc:
        workflow._narration_alignment(_run(), _node_run(), _run_state(strict_timestamps=True))

    assert exc.value.error.code == ErrorCode.provider_remote_failed
    assert exc.value.error.retryable is True
