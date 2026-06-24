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
    # 纯文生(无参考素材):字幕硬约束 + 信息流广告节奏 + 人物自然说话。
    p0 = _build_ad_prompt("买东西真方便", has_references=False)
    assert p0 == (
        "画面无任何字幕。保持无字幕，避免生成任何文字或字幕。"
        "画面中不出现标题、标语、歌词、台词文字、UI文字、Logo、水印或贴纸文案。"
        "只生成干净画面；真实环境中的门头、包装、价签可以自然出现。"
        "生成一条 15 秒信息流短视频广告，像本地生活商家在手机信息流里的自然推荐，"
        "整体真实、生活化、连贯。"
        "画面节奏：开场用门头或环境建立场景，中段用人物动作和商品细节承接卖点，"
        "结尾回到人物或门店形成到店记忆。"
        "画面用途是让用户快速知道这家店在哪里、卖什么、为什么方便。"
        "声音可以有人物自然说话和轻微环境声；如果有人说话，只生成口型和声音，画面不显示说话内容。\n"
        "人物在片中自然说出这段话，用于声音和口型，不是画面文字：\n"
        "买东西真方便"
    )
    assert p0.startswith("画面无任何字幕。")
    assert "保持无字幕，避免生成任何文字或字幕" in p0
    assert "台词文字" in p0
    assert "信息流短视频广告" in p0
    assert "画面节奏：开场用门头或环境建立场景" in p0
    assert "人物在片中自然说出这段话" in p0
    assert "画面不显示说话内容" in p0
    assert "{买东西真方便}" not in p0
    assert "抖音信息流广告" not in p0
    assert "配 BGM" not in p0
    # 带参考素材(老板娘出镜):追加出镜人物行。
    p1 = _build_ad_prompt("买东西真方便", has_references=True)
    assert p1.startswith(
        "画面无任何字幕。保持无字幕，避免生成任何文字或字幕。"
        "画面中不出现标题、标语、歌词、台词文字、UI文字、Logo、水印或贴纸文案。"
        "只生成干净画面；真实环境中的门头、包装、价签可以自然出现。"
        "生成一条 15 秒信息流短视频广告，像本地生活商家在手机信息流里的自然推荐，"
        "整体真实、生活化、连贯。"
        "画面节奏：开场用门头或环境建立场景，中段用人物动作和商品细节承接卖点，"
        "结尾回到人物或门店形成到店记忆。"
        "画面用途是让用户快速知道这家店在哪里、卖什么、为什么方便。"
        "声音可以有人物自然说话和轻微环境声；如果有人说话，只生成口型和声音，画面不显示说话内容。\n"
        "人物在片中自然说出这段话，用于声音和口型，不是画面文字：\n"
        "买东西真方便"
    )
    assert "参考素材定义出镜人物或场景风格，保持自然出镜和说话状态" in p1


def test_build_ad_prompt_flattens_multiline_script_to_avoid_caption_cues():
    prompt = _build_ad_prompt("第一句。\n第二句。\n\n第三句。", has_references=False)
    assert "第一句。 第二句。 第三句。" in prompt
    assert "第一句。\n第二句。" not in prompt


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
    assert call.input["ratio"] == "3:4"
    prompt = str(call.input["prompt"])
    assert prompt.startswith("画面无任何字幕。")
    assert "保持无字幕，避免生成任何文字或字幕" in prompt
    assert "信息流短视频广告" in prompt
    assert "人物在片中自然说出这段话" in prompt
    assert "画面不显示说话内容" in prompt
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
