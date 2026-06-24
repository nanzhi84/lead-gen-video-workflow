from __future__ import annotations

from packages.ai.gateway import ProviderResult
from packages.core.contracts import (
    ArtifactKind,
    DigitalHumanVideoRequest,
    NodeRun,
    NodeStatus,
    ProviderInvocation,
    ProviderOptionsSchemaRef,
    ProviderProfile,
    ProviderStatus,
    RunStatus,
    WorkflowRun,
)
from packages.core.storage.repository import Repository
from packages.production.pipeline._node_context import NodeContext
from packages.production.pipeline._run_state import RunState
from packages.production.pipeline.digital_human import (
    LocalRuntimeAdapter,
    seedance_t2v_template,
    template_for,
)
from packages.production.pipeline.node_sequence import SEEDANCE_T2V_SEQUENCE, expected_node_count
from packages.production.pipeline.nodes import seedance_generate_video, validate_request
from packages.production.pipeline.nodes.seedance_generate_video import _build_ad_prompt


def _output_kinds_by_node(template):
    return {spec.node_id: list(spec.output_artifact_kinds) for spec in template.nodes}


def test_seedance_template_registers_five_node_sequence():
    template = seedance_t2v_template()
    assert template.workflow_template_id == "seedance_t2v_v1"
    assert template.version == "v1"
    assert [spec.node_id for spec in template.nodes] == SEEDANCE_T2V_SEQUENCE
    assert SEEDANCE_T2V_SEQUENCE == [
        "ValidateRequest",
        "LoadCaseContext",
        "SeedanceGenerateVideo",
        "ExportSeedanceVideo",
        "FinalizeRunReport",
    ]
    assert expected_node_count("seedance_t2v_v1") == 5
    # No TTS / portrait / lipsync nodes in the seedance chain.
    assert "TTS" not in SEEDANCE_T2V_SEQUENCE
    assert "LipSync" not in SEEDANCE_T2V_SEQUENCE
    assert "PortraitPlanning" not in SEEDANCE_T2V_SEQUENCE


def test_template_for_dispatches_seedance():
    assert template_for("seedance_t2v_v1").workflow_template_id == "seedance_t2v_v1"


def test_seedance_node_outputs_and_provider_side_effect():
    template = seedance_t2v_template()
    output_kinds = _output_kinds_by_node(template)
    assert output_kinds["SeedanceGenerateVideo"] == [ArtifactKind.video_rendered]
    assert output_kinds["ExportSeedanceVideo"] == [
        ArtifactKind.video_finished,
        ArtifactKind.cover_image,
        ArtifactKind.publish_package,
    ]
    specs = {spec.node_id: spec for spec in template.nodes}
    # The paid Seedance call must be a declared side effect with a non-None
    # idempotency_key so resume never silently re-bills a generation.
    assert specs["SeedanceGenerateVideo"].side_effects == ["provider_call"]
    assert specs["SeedanceGenerateVideo"].idempotency_key is not None
    # The export node is pure assembly.
    assert specs["ExportSeedanceVideo"].side_effects == []


def _validate_ctx(request: DigitalHumanVideoRequest) -> NodeContext:
    repository = Repository()
    adapter = object.__new__(LocalRuntimeAdapter)
    adapter.repository = repository
    run = WorkflowRun(
        id="run_validate",
        job_id="job_validate",
        case_id=request.case_id,
        workflow_template_id=request.workflow_template_id,
        workflow_version="v1",
        status=RunStatus.running,
    )
    node_run = NodeRun(
        id="nr_validate",
        run_id=run.id,
        node_id="ValidateRequest",
        node_version="v1",
        status=NodeStatus.running,
        input_manifest_hash="sha256:test",
    )
    return NodeContext(adapter=adapter, run=run, node_run=node_run, state=RunState(request=request))


def test_build_ad_prompt_mirrors_boss_format():
    # 纯文生(无参考素材):口播音频 + 禁 BGM/字幕,不带出镜人物行。
    p0 = _build_ad_prompt("买东西真方便", has_references=False)
    assert p0 == (
        "请生成一条竖屏生活流短视频广告，生成自然中文旁白音频。"
        "画面里不要主动生成任何文字。"
        "禁止生成 BGM、背景音乐、音效铺底或任何非旁白音频；"
        "禁止生成字幕、逐字字幕、底部字幕、口播文字上屏、标题字卡、贴纸文字、歌词、花字、CTA 文字或额外文字叠加；"
        "只有真实拍摄场景中自然存在的文字可以保留，例如门头招牌、商品包装、价签。\n"
        "旁白台词如下，只用于配音朗读，不属于画面内容，绝对不要把这些台词显示成画面文字或字幕：\n"
        "买东西真方便"
    )
    assert "生成自然中文旁白音频" in p0
    assert "禁止生成 BGM" in p0
    assert "背景音乐" in p0
    assert "非旁白音频" in p0
    assert "禁止生成字幕" in p0
    assert "口播文字上屏" in p0
    assert "{买东西真方便}" not in p0
    assert "抖音信息流广告" not in p0
    assert "配 BGM" not in p0
    # 带参考素材(老板娘出镜):追加出镜人物行。
    p1 = _build_ad_prompt("买东西真方便", has_references=True)
    assert p1.startswith(
        "请生成一条竖屏生活流短视频广告，生成自然中文旁白音频。"
        "画面里不要主动生成任何文字。"
        "禁止生成 BGM、背景音乐、音效铺底或任何非旁白音频；"
        "禁止生成字幕、逐字字幕、底部字幕、口播文字上屏、标题字卡、贴纸文字、歌词、花字、CTA 文字或额外文字叠加；"
        "只有真实拍摄场景中自然存在的文字可以保留，例如门头招牌、商品包装、价签。\n"
        "旁白台词如下，只用于配音朗读，不属于画面内容，绝对不要把这些台词显示成画面文字或字幕：\n"
        "买东西真方便"
    )
    assert "出镜人物/场景见参考素材" in p1


class _StaticProviderProfiles:
    def __init__(self, profile: ProviderProfile) -> None:
        self.profile = profile

    def first_available(self, capability: str, *, include_sandbox: bool = True):
        return self.profile if self.profile.capability == capability else None


class _CapturingSeedanceGateway:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository
        self.calls = []

    def invoke(self, call):
        self.calls.append(call)
        artifact = self.repository.create_artifact(
            kind=ArtifactKind.video_rendered,
            payload_schema="uri-only",
            payload=None,
            case_id=call.case_id,
            run_id=call.run_id,
            node_run_id=call.node_run_id,
            uri="sandbox://video/seedance/test.mp4",
        )
        invocation = ProviderInvocation(
            id="pinv_seedance",
            case_id=call.case_id,
            run_id=call.run_id,
            node_run_id=call.node_run_id,
            provider_id="volcengine.seedance",
            model_id="doubao-seedance",
            provider_profile_id=call.provider_profile_id,
            capability_id=call.capability_id,
            status=ProviderStatus.succeeded,
        )
        return invocation, ProviderResult(
            output={"video_artifact_id": artifact.id, "video_uri": artifact.uri}
        )


def test_seedance_generate_video_requests_voiceover_without_bgm_or_captions():
    repository = Repository()
    profile = ProviderProfile(
        id="volcengine.seedance.test",
        provider_id="volcengine.seedance",
        model_id="doubao-seedance",
        capability="video.generate",
        display_name="Seedance",
        environment="prod",
        options_schema_ref=ProviderOptionsSchemaRef(schema_id="provider.video.options"),
    )
    gateway = _CapturingSeedanceGateway(repository)
    adapter = object.__new__(LocalRuntimeAdapter)
    adapter.repository = repository
    adapter.provider_profiles = _StaticProviderProfiles(profile)
    adapter.provider_gateway = gateway
    request = DigitalHumanVideoRequest(
        case_id="case_demo",
        script="买东西真方便",
        voice={"voice_id": ""},
        workflow_template_id="seedance_t2v_v1",
    )
    run = WorkflowRun(
        id="run_seedance",
        job_id="job_seedance",
        case_id=request.case_id,
        workflow_template_id=request.workflow_template_id,
        workflow_version="v1",
        status=RunStatus.running,
    )
    node_run = NodeRun(
        id="nr_seedance",
        run_id=run.id,
        node_id="SeedanceGenerateVideo",
        node_version="v1",
        status=NodeStatus.running,
        input_manifest_hash="sha256:test",
    )
    ctx = NodeContext(adapter=adapter, run=run, node_run=node_run, state=RunState(request=request))

    output = seedance_generate_video.run(ctx)

    assert output.artifacts[0].kind == ArtifactKind.video_rendered
    assert gateway.calls
    call = gateway.calls[0]
    assert call.input["generate_audio"] is True
    prompt = str(call.input["prompt"])
    assert "生成自然中文旁白音频" in prompt
    assert "禁止生成 BGM" in prompt
    assert "禁止生成字幕" in prompt
    assert "{买东西真方便}" not in prompt
    assert "抖音信息流广告" not in prompt
    assert "配 BGM" not in prompt


def test_validate_request_skips_voice_for_seedance_template():
    # A non-empty voice_id that does NOT exist would fail validation for a TTS
    # template; the seedance chain has no TTS node, so it must pass.
    ctx = _validate_ctx(
        DigitalHumanVideoRequest(
            case_id="case_demo",
            script="门头特写，暖光，产品摆放整齐。",
            voice={"voice_id": "voice_does_not_exist"},
            workflow_template_id="seedance_t2v_v1",
        )
    )
    output = validate_request.run(ctx)
    assert output.artifacts[0].kind == ArtifactKind.validated_production_spec
    assert output.artifacts[0].payload["workflow_template_id"] == "seedance_t2v_v1"
