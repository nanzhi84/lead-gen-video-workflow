"""SeedanceGenerateVideo node: one-shot ad video via Volcengine Ark.

Assembles an ad prompt (mirroring the boss's proven format: 指令 + 口播脚本 + 出镜
人物) from the request script (falling back to the case profile), resolves any
reference image/video assets to their source artifact URIs, and invokes the
``video.generate`` capability with native voiceover audio on but BGM/captions
explicitly disabled in the prompt. The provider downloads + stores the result,
so the real path returns a ``video.rendered`` artifact id; the sandbox path
returns only a fake uri, which this node bridges into a uri-only artifact so the
downstream export node has something to reference.
"""

from __future__ import annotations

from packages.ai.gateway import ProviderCall
from packages.core.config.settings import sandbox_fallback_allowed
from packages.core.contracts import ArtifactKind, ErrorCode
from packages.core.workflow import NodeExecutionError, NodeOutput
from packages.production.pipeline._node_context import NodeContext

_SEEDANCE_DURATION_SEC = 15
_SEEDANCE_RATIO = "3:4"
_SEEDANCE_RESOLUTION = "720p"

# Ad prompt template for voiceover-only Seedance ads. Keep the voiceover copy out
# of braces/quotes and collapse line breaks: video models can interpret visible
# delimiters or newline-separated script lines as subtitle cues.
#
# NOTE: the prompt is built from the request script only, so changing this template
# does NOT change the node's ``input_manifest_hash`` (which hashes node_id + request
# + artifact_refs, not the prompt) and there is no per-node version bump. A run that
# already produced a ``video.rendered`` here and is later *resumed* will reuse the
# old clip rather than re-render with a changed prompt. Editing this template only
# affects fresh runs; in-flight runs must be re-run (not resumed) to pick it up.
_AD_PROMPT_PREFIX = (
    "画面无任何字幕。保持无字幕，避免生成任何文字或字幕。"
    "画面中不出现标题、标语、歌词、台词文字、UI文字、Logo、水印或贴纸文案。"
    "只生成干净画面；真实环境中的门头、包装、价签可以自然出现。"
    "生成一条 15 秒信息流短视频广告，像本地生活商家在手机信息流里的自然推荐，"
    "整体真实、生活化、连贯。"
    "画面节奏：开场用门头或环境建立场景，中段用人物动作和商品细节承接卖点，"
    "结尾回到人物或门店形成到店记忆。"
    "画面用途是让用户快速知道这家店在哪里、卖什么、为什么方便。"
    "声音可以有人物自然说话和轻微环境声；如果有人说话，只生成口型和声音，画面不显示说话内容。"
)
_AD_PROMPT_REFERENCE_LINE = "参考素材定义出镜人物或场景风格，保持自然出镜和说话状态。"


def _build_ad_prompt(spoken_script: str, *, has_references: bool) -> str:
    lines = [
        _AD_PROMPT_PREFIX,
        "人物在片中自然说出这段话，用于声音和口型，不是画面文字：",
        _normalize_spoken_script(spoken_script),
    ]
    if has_references:
        lines.append(_AD_PROMPT_REFERENCE_LINE)
    return "\n".join(lines)


def _normalize_spoken_script(spoken_script: str) -> str:
    return " ".join(spoken_script.split())


def run(ctx: NodeContext) -> NodeOutput:
    state = ctx.state
    run = ctx.run
    node_run = ctx.node_run
    request = state.request

    spoken_script = (request.script or "").strip() or _compose_prompt_from_case(ctx)
    if not spoken_script:
        raise NodeExecutionError(
            ErrorCode.validation_missing_script,
            "Seedance 生成缺少口播脚本（脚本为空且无法从案例信息拼出）。",
        )

    references = _resolve_references(ctx)
    prompt = _build_ad_prompt(spoken_script, has_references=bool(references))

    profile = ctx.first_available_provider_profile(
        "video.generate", include_sandbox=sandbox_fallback_allowed()
    )
    if profile is None:
        raise NodeExecutionError(
            ErrorCode.provider_unsupported_option,
            "未配置可用的真实文生视频（Seedance）供应商。请在「设置」中配置并启用 "
            "capability=video.generate 的供应商及密钥。",
        )

    invocation, result = ctx.provider_gateway.invoke(
        ProviderCall(
            case_id=run.case_id,
            run_id=run.id,
            node_run_id=node_run.id,
            provider_profile_id=profile.id,
            capability_id="video.generate",
            input={
                "prompt": prompt,
                "duration_sec": _SEEDANCE_DURATION_SEC,
                "ratio": _SEEDANCE_RATIO,
                "resolution": _SEEDANCE_RESOLUTION,
                "generate_audio": True,
                "references": references,
            },
            idempotency_key=f"{run.id}:{node_run.id}:seedance",
        )
    )
    if result is None or invocation.error:
        # Video generation is not idempotent (a retry re-bills + re-generates), so
        # surface a hard failure for a human to act on rather than auto-retrying.
        raise NodeExecutionError(
            invocation.error.code if invocation.error else ErrorCode.provider_remote_failed,
            invocation.error.message if invocation.error else "Seedance 视频生成失败。",
            retryable=False,
        )

    artifact = _resolve_video_artifact(ctx, result)
    return NodeOutput(artifacts=[artifact], provider_invocation_ids=[invocation.id])


def _resolve_references(ctx: NodeContext) -> list[dict[str, str]]:
    """Map request.reference_asset_ids -> [{uri, kind}] (presigned later by provider).

    ``kind`` is "video" for video media assets, else "image" — the provider turns
    these into video_url / image_url content entries. ``source_artifact_for_asset``
    raises ``artifact_missing`` when the asset or its source uri is absent, so a
    missing reference fails the node loudly."""
    references: list[dict[str, str]] = []
    for asset_id in getattr(ctx.state.request, "reference_asset_ids", None) or []:
        artifact = ctx.source_artifact_for_asset(asset_id)
        media_asset = ctx.repository.media_assets.get(asset_id)
        kind = "video" if media_asset is not None and media_asset.kind == "video" else "image"
        references.append({"uri": artifact.uri, "kind": kind})
    return references


def _resolve_video_artifact(ctx: NodeContext, result):
    """Real path: provider already stored the video and returned an artifact id.
    Sandbox path: only a fake uri exists -> wrap it in a uri-only artifact."""
    artifact_id = result.output.get("video_artifact_id")
    if isinstance(artifact_id, str) and artifact_id in ctx.repository.artifacts:
        return ctx.repository.artifacts[artifact_id]
    video_uri = result.output.get("video_uri")
    if not isinstance(video_uri, str) or not video_uri:
        raise NodeExecutionError(
            ErrorCode.provider_remote_failed,
            "Seedance 供应商未返回可用的视频产物。",
        )
    return ctx.artifact(ArtifactKind.video_rendered, None, "uri-only", uri=video_uri)


def _compose_prompt_from_case(ctx: NodeContext) -> str:
    case = ctx.repository.cases.get(ctx.state.request.case_id)
    if case is None:
        return ""
    selling = getattr(case, "key_selling_points", None) or []
    bits = [
        getattr(case, "product", None),
        "、".join(selling),
        getattr(case, "ip_persona", None),
        getattr(case, "brand_voice", None),
    ]
    return "，".join(b for b in bits if b)
